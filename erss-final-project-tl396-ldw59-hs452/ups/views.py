import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie

from .forms import (
    PortalSearchForm,
    QuoteEstimateForm,
    RedirectShipmentForm,
    SignUpForm,
    SupportTicketForm,
    TrackingLookupForm,
)
from .models import SavedQuote, Shipment, ShipmentStatus, SupportTicket, SupportTicketStatus
from .services import (
    build_alert_feed,
    calculate_quote,
    create_shipment_from_amazon,
    create_support_ticket,
    get_service_locations,
    mark_loaded_from_amazon,
    portal_search,
    redirect_shipment,
    save_quote,
    visible_shipments_for_user,
)


def _shipment_for_user(user, tracking_number):
    if user.is_staff:
        return get_object_or_404(
            Shipment.objects.select_related("assigned_truck", "owner").prefetch_related("items", "events"),
            tracking_number=tracking_number,
        )

    shipment = Shipment.objects.select_related("assigned_truck", "owner").prefetch_related("items", "events").filter(
        tracking_number=tracking_number
    ).filter(owner=user).first()
    if shipment is None:
        shipment = (
            Shipment.objects.select_related("assigned_truck", "owner")
            .prefetch_related("items", "events")
            .filter(tracking_number=tracking_number, owner_reference__iexact=user.username)
            .first()
        )
    if shipment is None:
        raise Http404("Shipment not found.")
    return shipment


def _api_authorized(request):
    expected = settings.UPS_API_TOKEN
    if not expected:
        return True
    return request.headers.get("X-UPS-API-Key") == expected


def _api_error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def _json_payload(request):
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed JSON request body.") from exc


def _quote_history_for_user(user):
    queryset = SavedQuote.objects.all()
    if not getattr(user, "is_authenticated", False):
        return queryset.filter(created_by__isnull=True)
    if user.is_staff:
        return queryset
    return queryset.filter(created_by=user)


def _support_tickets_for_user(user):
    queryset = SupportTicket.objects.all()
    if not getattr(user, "is_authenticated", False):
        return queryset.none()
    if user.is_staff:
        return queryset

    filters = Q(owner=user)
    if user.email:
        filters |= Q(email__iexact=user.email)
    return queryset.filter(filters).distinct()


def _tracking_context(tracking_number):
    shipment = _tracking_shipment_lookup(tracking_number)
    if shipment is None:
        raise Http404("Shipment not found.")
    return {
        "shipment": shipment,
        "can_redirect": shipment.can_redirect(),
    }


def _tracking_shipment_lookup(identifier):
    normalized = identifier.strip()
    if not normalized:
        return None

    queryset = Shipment.objects.select_related("assigned_truck").prefetch_related("items", "events")
    filters = Q(tracking_number__iexact=normalized)
    if normalized.isdigit():
        filters |= Q(package_id=int(normalized))
    return queryset.filter(filters).first()


def home(request):
    form = TrackingLookupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        shipment = _tracking_shipment_lookup(form.cleaned_data["tracking_number"])
        if shipment is not None:
            return redirect("ups:tracking-result", tracking_number=shipment.tracking_number)
        messages.error(request, "Tracking number invalid or not found.", extra_tags="popup")

    recent_shipments = Shipment.objects.select_related("assigned_truck").order_by("-updated_at")[:8]
    return render(
        request,
        "ups/tracking_lookup.html",
        {
            "form": form,
            "recent_shipments": recent_shipments,
        },
    )


def search_results(request):
    query = request.GET.get("query", "").strip()
    form = PortalSearchForm(initial={"query": query})
    results = portal_search(query, request.user if request.user.is_authenticated else None) if query else None
    return render(
        request,
        "ups/search_results.html",
        {
            "form": form,
            "query": query,
            "results": results,
        },
    )


def shipping_overview(request):
    shipments = (
        visible_shipments_for_user(request.user)
        if request.user.is_authenticated
        else Shipment.objects.select_related("assigned_truck", "owner").order_by("-updated_at")
    )
    support_tickets = (
        _support_tickets_for_user(request.user)
        if request.user.is_authenticated
        else SupportTicket.objects.filter(status__in=[SupportTicketStatus.OPEN, SupportTicketStatus.IN_PROGRESS])
    )
    quotes = _quote_history_for_user(request.user) if request.user.is_authenticated else SavedQuote.objects.all()

    counts = {
        "total": shipments.count(),
        "warehouse_flow": shipments.filter(
            status__in=[
                ShipmentStatus.CREATED,
                ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
                ShipmentStatus.WAITING_FOR_PICKUP,
                ShipmentStatus.LOADING,
                ShipmentStatus.LOADED,
            ]
        ).count(),
        "out_for_delivery": shipments.filter(status=ShipmentStatus.OUT_FOR_DELIVERY).count(),
        "delivered": shipments.filter(status=ShipmentStatus.DELIVERED).count(),
        "open_tickets": support_tickets.filter(
            status__in=[SupportTicketStatus.OPEN, SupportTicketStatus.IN_PROGRESS]
        ).count(),
        "saved_quotes": quotes.count(),
    }
    return render(
        request,
        "ups/shipping_overview.html",
        {
            "counts": counts,
            "recent_shipments": shipments[:6],
            "recent_quotes": quotes[:4],
            "support_tickets": support_tickets[:4],
            "locations": get_service_locations()[:3],
        },
    )


def quote_overview(request):
    selected_quote = None
    quote_result = None

    if request.method == "POST":
        form = QuoteEstimateForm(request.POST)
        if form.is_valid():
            quote_result = calculate_quote(form.cleaned_data)
            selected_quote = save_quote(form.cleaned_data, request.user)
            messages.success(
                request,
                f"Estimate saved for {selected_quote.estimated_cost_display} with "
                f"{quote_result['estimated_business_days']} business day service.",
            )
    else:
        selected_quote_id = request.GET.get("quote")
        if selected_quote_id:
            selected_quote = get_object_or_404(_quote_history_for_user(request.user), pk=selected_quote_id)
            quote_result = calculate_quote(
                {
                    "service_level": selected_quote.service_level,
                    "origin_x": selected_quote.origin_x,
                    "origin_y": selected_quote.origin_y,
                    "destination_x": selected_quote.destination_x,
                    "destination_y": selected_quote.destination_y,
                    "package_count": selected_quote.package_count,
                    "total_weight_lbs": selected_quote.total_weight_lbs,
                }
            )
            form = QuoteEstimateForm(
                initial={
                    "service_level": selected_quote.service_level,
                    "origin_x": selected_quote.origin_x,
                    "origin_y": selected_quote.origin_y,
                    "destination_x": selected_quote.destination_x,
                    "destination_y": selected_quote.destination_y,
                    "package_count": selected_quote.package_count,
                    "total_weight_lbs": selected_quote.total_weight_lbs,
                }
            )
        else:
            form = QuoteEstimateForm()

    recent_quotes = _quote_history_for_user(request.user) if request.user.is_authenticated else SavedQuote.objects.all()
    return render(
        request,
        "ups/quote_overview.html",
        {
            "form": form,
            "quote_result": quote_result,
            "selected_quote": selected_quote,
            "recent_quotes": recent_quotes[:6],
        },
    )


def support_center(request):
    initial = {}
    if request.user.is_authenticated and request.user.email:
        initial["email"] = request.user.email

    created_ticket = None
    if request.method == "POST":
        form = SupportTicketForm(request.POST, initial=initial)
        if form.is_valid():
            created_ticket = create_support_ticket(form.cleaned_data, request.user)
            messages.success(request, f"Support request #{created_ticket.pk} has been submitted.")
            form = SupportTicketForm(initial=initial)
    else:
        form = SupportTicketForm(initial=initial)

    tickets = _support_tickets_for_user(request.user)
    status_counts = {
        "open": tickets.filter(status=SupportTicketStatus.OPEN).count(),
        "in_progress": tickets.filter(status=SupportTicketStatus.IN_PROGRESS).count(),
        "resolved": tickets.filter(status=SupportTicketStatus.RESOLVED).count(),
    }
    return render(
        request,
        "ups/support_center.html",
        {
            "form": form,
            "created_ticket": created_ticket,
            "recent_tickets": tickets[:6],
            "status_counts": status_counts,
        },
    )


def alerts_center(request):
    shipments = (
        visible_shipments_for_user(request.user)
        if request.user.is_authenticated
        else Shipment.objects.select_related("assigned_truck").order_by("-updated_at")
    )
    support_tickets = _support_tickets_for_user(request.user)
    alert_feed = build_alert_feed(request.user if request.user.is_authenticated else None)
    counts = {
        "total": len(alert_feed),
        "shipment": sum(1 for item in alert_feed if item["kind"] == "shipment"),
        "support": sum(1 for item in alert_feed if item["kind"] == "support"),
        "exceptions": shipments.filter(status=ShipmentStatus.ERROR).count(),
    }
    return render(
        request,
        "ups/alerts_center.html",
        {
            "counts": counts,
            "alert_feed": alert_feed,
            "recent_shipments": shipments[:5],
            "recent_tickets": support_tickets[:5],
        },
    )


def locations_center(request):
    query = request.GET.get("query", "").strip()
    locations = get_service_locations(query)
    type_counts = {}
    for location in get_service_locations():
        type_counts[location["type"]] = type_counts.get(location["type"], 0) + 1

    return render(
        request,
        "ups/locations_center.html",
        {
            "query": query,
            "locations": locations,
            "location_type_counts": [
                {"label": label, "count": count}
                for label, count in sorted(type_counts.items(), key=lambda item: item[0])
            ],
        },
    )


@login_required
def dashboard(request):
    shipments = visible_shipments_for_user(request.user)
    counts = {
        "total": shipments.count(),
        "pending": shipments.filter(status__in=[
            ShipmentStatus.CREATED,
            ShipmentStatus.EN_ROUTE_TO_WAREHOUSE,
            ShipmentStatus.WAITING_FOR_PICKUP,
            ShipmentStatus.LOADING,
            ShipmentStatus.LOADED,
        ]).count(),
        "out_for_delivery": shipments.filter(status=ShipmentStatus.OUT_FOR_DELIVERY).count(),
        "delivered": shipments.filter(status=ShipmentStatus.DELIVERED).count(),
    }
    return render(
        request,
        "ups/dashboard.html",
        {
            "counts": counts,
            "recent_shipments": shipments[:8],
        },
    )


def tracking_lookup(request):
    return home(request)


def public_tracking_result(request, tracking_number):
    shipment = _tracking_shipment_lookup(tracking_number)
    if shipment is None:
        messages.error(request, "Tracking number invalid or not found.", extra_tags="popup")
        return redirect("ups:home")
    context = {
        "shipment": shipment,
        "can_redirect": shipment.can_redirect(),
    }
    return render(request, "ups/tracking_result.html", context)


@ensure_csrf_cookie
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("ups:dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, "Account created. You are now signed in.")
            return redirect("ups:dashboard")
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {"form": form})


@login_required
def shipment_list(request):
    shipments = visible_shipments_for_user(request.user)
    return render(request, "ups/shipment_list.html", {"shipments": shipments})


@login_required
def shipment_detail(request, tracking_number):
    shipment = _shipment_for_user(request.user, tracking_number)
    form = RedirectShipmentForm(shipment=shipment)
    return render(
        request,
        "ups/shipment_detail.html",
        {
            "shipment": shipment,
            "form": form,
        },
    )


@login_required
def redirect_shipment_view(request, tracking_number):
    shipment = _shipment_for_user(request.user, tracking_number)
    form = RedirectShipmentForm(request.POST, shipment=shipment)
    if not form.is_valid():
        for error in form.errors.get("__all__", []):
            messages.error(request, error)
        return redirect("ups:shipment-detail", tracking_number=tracking_number)

    try:
        redirect_shipment(
            shipment,
            form.cleaned_data["destination_x"],
            form.cleaned_data["destination_y"],
            actor=request.user.username,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Shipment redirect saved.")
    return redirect("ups:shipment-detail", tracking_number=tracking_number)


@csrf_exempt
def shipment_create_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)
    if not _api_authorized(request):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        shipment = create_shipment_from_amazon(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    return JsonResponse(shipment.as_tracking_dict(), status=201)


@csrf_exempt
def pickup_api(request):
    if request.method != "POST":
        return _api_error("Method not allowed.", status=405)

    try:
        payload = _json_payload(request)
        shipment = create_shipment_from_amazon(payload)
    except ValueError as exc:
        return _api_error(str(exc), status=400)

    return JsonResponse({"truck_id": shipment.assigned_truck.truck_id}, status=200)


@csrf_exempt
def package_loaded_api(request):
    if request.method != "POST":
        return _api_error("Method not allowed.", status=405)

    try:
        payload = _json_payload(request)
        shipment = mark_loaded_from_amazon(
            package_id=int(payload["package_id"]),
            truck_id=int(payload["truck_id"]),
            destination_x=int(payload["dest_x"]),
            destination_y=int(payload["dest_y"]),
        )
    except KeyError as exc:
        return _api_error(f"Missing required field: {exc.args[0]}", status=400)
    except Shipment.DoesNotExist:
        return _api_error("Unknown package_id.", status=404)
    except ValueError as exc:
        return _api_error(str(exc), status=400)

    return JsonResponse({}, status=200)


@csrf_exempt
def redirect_by_package_api(request):
    if request.method != "POST":
        return _api_error("Method not allowed.", status=405)

    try:
        payload = _json_payload(request)
    except ValueError as exc:
        return _api_error(str(exc), status=400)

    try:
        shipment = Shipment.objects.get(package_id=int(payload["package_id"]))
    except KeyError as exc:
        return _api_error(f"Missing required field: {exc.args[0]}", status=400)
    except (TypeError, ValueError):
        return _api_error("package_id must be an integer.", status=400)
    except Shipment.DoesNotExist:
        return _api_error("Unknown package_id.", status=404)

    try:
        redirect_shipment(
            shipment,
            payload["dest_x"],
            payload["dest_y"],
            actor="amazon",
        )
    except KeyError as exc:
        return _api_error(f"Missing required field: {exc.args[0]}", status=400)
    except ValueError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=200)

    return JsonResponse({"success": True, "message": "Delivery address updated."}, status=200)


def shipment_status_api(request, tracking_number):
    shipment = get_object_or_404(
        Shipment.objects.select_related("assigned_truck", "owner").prefetch_related("items", "events"),
        tracking_number=tracking_number,
    )
    return JsonResponse(shipment.as_tracking_dict())


@csrf_exempt
def shipment_redirect_api(request, tracking_number):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)

    shipment = get_object_or_404(Shipment, tracking_number=tracking_number)
    authenticated_owner = request.user.is_authenticated and (
        request.user.is_staff
        or shipment.owner_id == request.user.id
        or shipment.owner_reference.lower() == request.user.username.lower()
    )
    if not authenticated_owner and not _api_authorized(request):
        return JsonResponse({"detail": "Unauthorized."}, status=401)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        shipment = redirect_shipment(
            shipment,
            payload["destination_x"],
            payload["destination_y"],
            actor=request.user.username if request.user.is_authenticated else "api",
        )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"detail": str(exc)}, status=400)

    return JsonResponse(shipment.as_tracking_dict())
