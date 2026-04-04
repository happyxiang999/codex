import asyncio
from types import SimpleNamespace

from src.web.routes import accounts as accounts_routes
from src.web.routes import payment as payment_routes
from src.web.routes import settings as settings_routes
import src.web.auto_quick_refresh_scheduler as scheduler_mod


def test_get_auto_quick_refresh_settings_includes_runtime(monkeypatch):
    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SimpleNamespace(
            auto_quick_refresh_enabled=True,
            auto_quick_refresh_interval_minutes=25,
            auto_quick_refresh_retry_limit=1,
        ),
    )
    monkeypatch.setattr(
        scheduler_mod,
        "auto_quick_refresh_scheduler",
        SimpleNamespace(snapshot=lambda: {"running": False, "last_status": "idle", "logs": []}),
    )

    result = asyncio.run(settings_routes.get_auto_quick_refresh_settings())

    assert result["enabled"] is True
    assert result["interval_minutes"] == 25
    assert result["retry_limit"] == 1
    assert result["runtime"]["last_status"] == "idle"


def test_update_auto_quick_refresh_settings_persists_and_runs_now(monkeypatch):
    update_calls = []

    class DummyScheduler:
        def __init__(self):
            self.notified = 0
            self.run_now_calls = []

        def notify_schedule_updated(self):
            self.notified += 1
            return {"running": False, "logs": [{"level": "info", "message": "updated"}]}

        def request_run_now(self, reason="manual"):
            self.run_now_calls.append(reason)
            return {"running": True, "reason": reason, "logs": [{"level": "info", "message": "run-now"}]}

    dummy_scheduler = DummyScheduler()

    monkeypatch.setattr(settings_routes, "update_settings", lambda **kwargs: update_calls.append(kwargs))
    monkeypatch.setattr(scheduler_mod, "auto_quick_refresh_scheduler", dummy_scheduler)

    result = asyncio.run(
        settings_routes.update_auto_quick_refresh_settings(
            settings_routes.AutoQuickRefreshSettingsRequest(
                enabled=True,
                interval_minutes=15,
                retry_limit=3,
                run_now=True,
            )
        )
    )

    assert result["success"] is True
    assert update_calls == [
        {
            "auto_quick_refresh_enabled": True,
            "auto_quick_refresh_interval_minutes": 15,
            "auto_quick_refresh_retry_limit": 3,
        }
    ]
    assert dummy_scheduler.notified == 1
    assert dummy_scheduler.run_now_calls == ["settings_save"]
    assert result["runtime"]["running"] is True


def test_has_active_batch_operations_detects_busy_domain_tasks(monkeypatch):
    monkeypatch.setattr(
        accounts_routes.task_manager,
        "list_domain_tasks",
        lambda domain, limit=50: [{"status": "running"}] if domain == "accounts" else [],
    )

    assert accounts_routes.has_active_batch_operations() is True


def test_run_quick_refresh_workflow_combines_validate_and_subscription(monkeypatch):
    monkeypatch.setattr(accounts_routes, "_get_quick_refresh_candidate_ids", lambda: [11, 22, 33])
    monkeypatch.setattr(accounts_routes, "_get_proxy", lambda request_proxy=None: "http://mock-proxy")
    monkeypatch.setattr(
        accounts_routes,
        "_run_batch_validate_tokens",
        lambda request: {
            "valid_count": 2,
            "invalid_count": 1,
            "details": [
                {"id": 11, "valid": True, "error": None},
                {"id": 22, "valid": False, "error": "expired"},
                {"id": 33, "valid": True, "error": None},
            ],
        },
    )
    monkeypatch.setattr(
        payment_routes,
        "batch_check_subscription",
        lambda request: {
            "success_count": len(request.ids),
            "failed_count": 0,
            "details": [
                {"id": account_id, "success": True, "subscription_type": "plus"}
                for account_id in request.ids
            ],
        },
    )

    result = accounts_routes.run_quick_refresh_workflow(source="auto:test")

    assert result["candidate_count"] == 3
    assert result["proxy_used"] == "http://mock-proxy"
    assert result["validate"]["total"] == 3
    assert result["validate"]["valid_count"] == 2
    assert result["subscription"]["total"] == 2
    assert result["subscription"]["success_count"] == 2


def test_batch_validate_tokens_async_registers_task_and_submits_worker(monkeypatch):
    register_calls = []
    submit_calls = []

    def fake_register_domain_task(**kwargs):
        register_calls.append(kwargs)
        return {
            "id": kwargs["task_id"],
            "domain": kwargs["domain"],
            "task_type": kwargs["task_type"],
            "status": "pending",
            "paused": False,
            "progress": kwargs["progress"],
        }

    def fake_submit(fn, task_id, request):
        submit_calls.append((fn, task_id, request))
        return SimpleNamespace()

    monkeypatch.setattr(accounts_routes, "_resolve_batch_validate_account_ids", lambda request: [101, 202, 303])
    monkeypatch.setattr(accounts_routes.task_manager, "register_domain_task", fake_register_domain_task)
    monkeypatch.setattr(accounts_routes.task_manager, "executor", SimpleNamespace(submit=fake_submit))

    request = accounts_routes.BatchValidateRequest(ids=[101, 202, 303], select_all=False)
    result = asyncio.run(accounts_routes.batch_validate_tokens_async(request))

    assert result["domain"] == "accounts"
    assert result["task_type"] == accounts_routes.ACCOUNT_ASYNC_TASK_VALIDATE
    assert result["progress"] == {"completed": 0, "total": 3}
    assert len(register_calls) == 1
    assert len(submit_calls) == 1
    assert submit_calls[0][1] == result["id"]
    assert submit_calls[0][2] == request


def test_get_account_async_task_returns_snapshot(monkeypatch):
    snapshot = {
        "id": "accounts-batch_validate-demo",
        "domain": "accounts",
        "task_type": accounts_routes.ACCOUNT_ASYNC_TASK_VALIDATE,
        "status": "running",
        "progress": {"completed": 1, "total": 2},
    }
    monkeypatch.setattr(accounts_routes.task_manager, "get_domain_task", lambda domain, task_id: snapshot)

    result = asyncio.run(accounts_routes.get_account_async_task("accounts-batch_validate-demo"))

    assert result == snapshot


def test_batch_check_subscription_async_registers_task_and_submits_worker(monkeypatch):
    register_calls = []
    submit_calls = []

    def fake_register_domain_task(**kwargs):
        register_calls.append(kwargs)
        return {
            "id": kwargs["task_id"],
            "domain": kwargs["domain"],
            "task_type": kwargs["task_type"],
            "status": "pending",
            "paused": False,
            "progress": kwargs["progress"],
        }

    def fake_submit(fn, task_id, request):
        submit_calls.append((fn, task_id, request))
        return SimpleNamespace()

    monkeypatch.setattr(payment_routes, "_resolve_batch_subscription_account_ids", lambda request: [1, 2])
    monkeypatch.setattr(payment_routes.task_manager, "register_domain_task", fake_register_domain_task)
    monkeypatch.setattr(payment_routes.task_manager, "executor", SimpleNamespace(submit=fake_submit))

    request = payment_routes.BatchCheckSubscriptionRequest(ids=[1, 2], select_all=False)
    result = payment_routes.batch_check_subscription_async(request)

    assert result["domain"] == "payment"
    assert result["task_type"] == payment_routes.PAYMENT_OP_TASK_SUBSCRIPTION
    assert result["progress"] == {"completed": 0, "total": 2}
    assert len(register_calls) == 1
    assert len(submit_calls) == 1
    assert submit_calls[0][1] == result["id"]
    assert submit_calls[0][2] == request


def test_get_payment_op_task_returns_snapshot(monkeypatch):
    snapshot = {
        "id": "payment-batch_check_subscription-demo",
        "domain": "payment",
        "task_type": payment_routes.PAYMENT_OP_TASK_SUBSCRIPTION,
        "status": "running",
        "progress": {"completed": 1, "total": 3},
    }
    monkeypatch.setattr(payment_routes.task_manager, "get_domain_task", lambda domain, task_id: snapshot)

    result = payment_routes.get_payment_op_task("payment-batch_check_subscription-demo")

    assert result == snapshot
