from django.urls import path

from . import views


urlpatterns = [
    path("events/", views.events_view),
    path("events/<str:event_id>/reverse/", views.reverse_event_view),
    path("events/<str:event_id>/", views.event_detail_view),
    path("redeem/", views.redeem_view),
    path("users/", views.users_view),
    path("users/<int:user_id>/", views.user_detail_view),
    path("balance/", views.user_balance_view),
    path("ledger/", views.user_ledger_view),
    path("users/<int:user_id>/balance/", views.user_balance_view),
    path("users/<int:user_id>/ledger/", views.user_ledger_view),
    path("reward-rules/", views.reward_rules_view),
    path("reward-rules/<int:rule_id>/", views.reward_rule_detail_view),
    path("rewards/", views.rewards_view),
    path("rewards/<int:reward_id>/", views.reward_detail_view),
]
