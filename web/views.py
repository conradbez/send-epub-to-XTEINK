import shutil

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from library import storage
from library.ingest import ingest
from library.models import Book, Device

from .forms import DeviceForm, SignupForm


def signup(request):
    """Open registration: each account gets its own shelf and devices."""
    if request.user.is_authenticated:
        return redirect("shelf")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Welcome. Upload your first book below.")
            return redirect("shelf")
    else:
        form = SignupForm()

    return render(request, "web/signup.html", {"form": form})


@login_required
def shelf(request):
    books = Book.objects.filter(owner=request.user)
    query = request.GET.get("q", "").strip()
    if query:
        books = books.filter(
            Q(title__icontains=query)
            | Q(author__icontains=query)
            | Q(series__icontains=query)
        )
    return render(
        request,
        "web/shelf.html",
        {
            "books": books,
            "query": query,
            "total": Book.objects.filter(owner=request.user).count(),
        },
    )


@login_required
@require_POST
def upload(request):
    uploads = request.FILES.getlist("epub")
    if not uploads:
        messages.error(request, "No file chosen.")
        return redirect("shelf")

    added, rejected = [], []
    for uploaded in uploads:
        result = ingest(request.user, uploaded)
        if result.ok:
            added.append(result.book.title)
        else:
            rejected.append(f"{result.filename}: {result.error}")

    if added:
        messages.success(
            request,
            f"Added {len(added)} book{'s' if len(added) != 1 else ''}: "
            + ", ".join(added[:5])
            + (" …" if len(added) > 5 else ""),
        )
    for problem in rejected:
        messages.error(request, problem)
    return redirect("shelf")


@login_required
@require_POST
def delete_book(request, pk):
    book = get_object_or_404(Book, pk=pk, owner=request.user)
    title = book.title
    book.delete_with_blobs()
    messages.success(request, f"Removed “{title}”.")
    return redirect("shelf")


@login_required
def cover(request, pk):
    book = get_object_or_404(Book, pk=pk, owner=request.user)
    if not book.has_cover or not book.cover_path.exists():
        raise Http404
    response = FileResponse(open(book.cover_path, "rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@login_required
def devices(request):
    if request.method == "POST":
        form = DeviceForm(request.POST)
        if form.is_valid():
            device = Device.objects.create(
                user=request.user, name=form.cleaned_data["name"]
            )
            messages.success(
                request, f"Added {device.name}. Its catalog link is below."
            )
            return redirect("devices")
    else:
        form = DeviceForm()

    return render(
        request,
        "web/devices.html",
        {"form": form, "devices": _devices_for(request)},
    )


@login_required
@require_POST
def device_reset(request, pk):
    device = get_object_or_404(Device, pk=pk, user=request.user)
    device.rotate_token()
    messages.success(
        request,
        f"New link for {device.name}. The old one stopped working — paste the "
        "new one into that reader.",
    )
    return redirect(request.POST.get("next") or "devices")


@login_required
@require_POST
def device_rename(request, pk):
    device = get_object_or_404(Device, pk=pk, user=request.user)
    name = request.POST.get("name", "").strip()
    if name:
        device.name = name[:100]
        device.save(update_fields=["name"])
        messages.success(request, "Renamed.")
    return redirect("devices")


@login_required
@require_POST
def device_revoke(request, pk):
    device = get_object_or_404(Device, pk=pk, user=request.user)
    name = device.name
    device.delete()
    messages.success(request, f"Revoked {name}. It can no longer reach the catalog.")
    return redirect("devices")


@login_required
def help_page(request):
    usage = shutil.disk_usage(settings.DATA_DIR)
    library_bytes = (
        Book.objects.filter(owner=request.user).aggregate(total=Sum("size"))["total"]
        or 0
    )
    return render(
        request,
        "web/help.html",
        {
            "devices": _devices_for(request),
            "form": DeviceForm(),
            "book_count": Book.objects.filter(owner=request.user).count(),
            "library_bytes": library_bytes,
            "blob_bytes": storage.dir_size(settings.BOOKS_DIR),
            "disk_used_pct": round(usage.used / usage.total * 100) if usage.total else 0,
            "disk_free": usage.free,
            "disk_total": usage.total,
            "insecure_host": not request.is_secure(),
        },
    )


def _devices_for(request):
    """Devices, each carrying the absolute catalog URL to paste into it."""
    devices = list(
        Device.objects.filter(user=request.user)
        .annotate(delivered=Count("deliveries"))
        .order_by("name")
    )
    for device in devices:
        device.catalog_url = request.build_absolute_uri(device.catalog_path)
    return devices
