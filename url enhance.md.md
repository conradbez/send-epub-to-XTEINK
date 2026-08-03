URL typing help page enhancements



	1.	On the reader: Home → File Transfer → Join Network (it’s already on your wifi).
	2.	The reader displays its address. http://crosspoint.local/ is preferred where supported, with the IP as fallback, and the reader shows a QR code for opening the web interface. ￼
	3.	On your phone: scan the QR, or type the short address once.
	4.	Your library’s /help/ page is open in another tab — tap Copy on the catalog URL.
	5.	In the reader’s web UI: <cite name="opds-card" index="40-1">the OPDS Servers card lets you add, edit, or delete entries</cite> — paste, save.
	6.	Exit File Transfer mode. The server stops when you leave that mode. ￼

Two tabs in the phone browser, one paste, no on-device keyboard at all.

Two things this changes in the design:

	•	The /help/ page should lead with this route and treat on-device entry as the fallback, not the reverse. The copy button becomes the single most important element on the page.
	•	It strengthens the capability-URL argument: one field to paste instead of three, and the web UI never shows passwords back after saving, ￼ so a mistyped Basic auth password is invisible to debug. A token URL either works or doesn’t.