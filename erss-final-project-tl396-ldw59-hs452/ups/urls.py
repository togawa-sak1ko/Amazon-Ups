from django.urls import path

from . import views


app_name = "ups"


urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/signup/", views.signup_view, name="signup"),
    path("pickup", views.pickup_api, name="pickup-api"),
    path("package-loaded", views.package_loaded_api, name="package-loaded-api"),
    path("redirect", views.redirect_by_package_api, name="redirect-by-package-api"),
    path("search/", views.search_results, name="search-results"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("tracking/", views.tracking_lookup, name="tracking-lookup"),
    path("shipping/", views.shipping_overview, name="shipping-overview"),
    path("quote/", views.quote_overview, name="quote-overview"),
    path("support/", views.support_center, name="support-center"),
    path("alerts/", views.alerts_center, name="alerts-center"),
    path("locations/", views.locations_center, name="locations-center"),
    path("tracking/<str:tracking_number>/", views.public_tracking_result, name="tracking-result"),
    path("shipments/", views.shipment_list, name="shipment-list"),
    path("shipments/<str:tracking_number>/", views.shipment_detail, name="shipment-detail"),
    path("shipments/<str:tracking_number>/redirect/", views.redirect_shipment_view, name="shipment-redirect"),
    path("api/shipments/", views.shipment_create_api, name="shipment-create-api"),
    path(
        "api/shipments/<str:tracking_number>/status/",
        views.shipment_status_api,
        name="shipment-status-api",
    ),
    path(
        "api/shipments/<str:tracking_number>/redirect/",
        views.shipment_redirect_api,
        name="shipment-redirect-api",
    ),
]
