import shutil

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from library import storage
from library.ingest import ingest
from library.models import Book, Device

from .forms import DeviceForm


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
            device, password = Device.create_with_credentials(
                request.user, form.cleaned_data["name"]
            )
            request.session["new_credential"] = {
                "device_id": device.pk,
                "name": device.name,
                "basic_user": device.basic_user,
                "password": password,
            }
            return redirect("devices")
    else:
        form = DeviceForm()

    return render(
        request,
        "web/devices.html",
        {
            "form": form,
            "devices": _devices_for(request.user),
            "new_credential": request.session.pop("new_credential", None),
            "catalog_url": request.build_absolute_uri("/opds/"),
        },
    )


@login_required
@require_POST
def device_reset(request, pk):
    device = get_object_or_404(Device, pk=pk, user=request.user)
    request.session["new_credential"] = {
        "device_id": device.pk,
        "name": device.name,
        "basic_user": device.basic_user,
        "password": device.reset_password(),
    }
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
        Book.objects.aggregate(total=Sum("size"))["total"] or 0
    )
    return render(
        request,
        "web/help.html",
        {
            "catalog_url": request.build_absolute_uri("/opds/"),
            "devices": _devices_for(request.user),
            "form": DeviceForm(),
            "new_credential": request.session.pop("new_credential", None),
            "book_count": Book.objects.filter(owner=request.user).count(),
            "library_bytes": library_bytes,
            "blob_bytes": storage.dir_size(settings.BOOKS_DIR),
            "disk_used_pct": round(usage.used / usage.total * 100) if usage.total else 0,
            "disk_free": usage.free,
            "disk_total": usage.total,
            "insecure_host": not request.is_secure(),
        },
    )


def _devices_for(user):
    return (
        Device.objects.filter(user=user)
        .annotate(delivered=Count("deliveries"))
        .order_by("name")
    )
