import os
from typing import Generator

import pytest
import responses
from django.utils import timezone
from faker import Faker

from django_acquiring import domain, enums, models
from django_acquiring.providers import paypal
from tests.factories import PaymentAttemptFactory, PaymentMethodFactory

fake = Faker()


@responses.activate
@pytest.mark.django_db
def test_givenACorrectPaymentMethod_whenRunningPayPalCreateOrder_thenItReturnsRedirectAction(
    fake_os_environ: Generator,
) -> None:
    payment_method = PaymentMethodFactory(payment_attempt=PaymentAttemptFactory()).to_domain()

    responses.add(
        responses.POST,
        f"{os.environ['PAYPAL_BASE_URL']}v1/oauth2/token",
        json={
            "scope": "",
            "access_token": fake.password(length=40, special_chars=False, upper_case=False),
            "token_type": "Bearer",
            "app_id": "APP-S3CR3T",
            "expires_in": 31668,
            "nonce": f"{timezone.now().isoformat()}-{fake.password(length=40, special_chars=False, upper_case=False)}",
        },
        status=201,
        content_type="application/json",
    )

    block = paypal.blocks.PayPalCreateOrder(
        adapter=paypal.adapter.PayPalAdapter(
            base_url=os.environ["PAYPAL_BASE_URL"],
            client_id=os.environ["PAYPAL_CLIENT_ID"],
            client_secret=os.environ["PAYPAL_CLIENT_SECRET"],
        )
    )

    fake_create_time = timezone.now().isoformat()
    fake_id = fake.password(length=10, special_chars=False, upper_case=False).upper()
    approve_url = f"{fake.url()}?token={fake_id}"
    responses.add(
        responses.Response(
            responses.POST,
            f"{os.environ['PAYPAL_BASE_URL']}v2/checkout/orders",
            json={
                "create_time": fake_create_time,
                "id": fake_id,
                "intent": paypal.domain.OrderIntentEnum.CAPTURE,
                "links": [
                    {"href": fake.url(), "method": "GET", "rel": "self"},
                    {"href": approve_url, "method": "GET", "rel": "approve"},
                    {"href": fake.url(), "method": "PATCH", "rel": "update"},
                    {"href": fake.url(), "method": "POST", "rel": "capture"},
                ],
                "purchase_units": [
                    {
                        "amount": {"currency_code": "USD", "value": "10.00"},
                        "payee": {
                            "email_address": fake.email(),
                            "merchant_id": fake.password(length=10, special_chars=False, upper_case=False).upper(),
                        },
                        "reference_id": fake.uuid4(),
                    }
                ],
                "status": paypal.domain.PayPalStatusEnum.CREATED,
            },
        )
    )

    response = block.run(payment_method)

    assert response == domain.BlockResponse(
        status=enums.OperationStatusEnum.COMPLETED,
        actions=[{"redirect_url": approve_url}],
        error_message=None,
    )

    assert models.BlockEvent.objects.count() == 2
    block_events = models.BlockEvent.objects.order_by("created_at")
    assert [block.status for block in block_events] == [
        enums.OperationStatusEnum.STARTED,
        enums.OperationStatusEnum.COMPLETED,
    ]
