from datetime import datetime
from typing import Type
from uuid import uuid4

import pytest

from django_acquiring import domain, models, protocols, repositories
from django_acquiring.domain import decision_logic as dl
from django_acquiring.enums import OperationStatusEnum, OperationTypeEnum
from tests.factories import PaymentAttemptFactory, PaymentMethodFactory, PaymentOperationFactory

COMPLETED_STATUS = [OperationStatusEnum.COMPLETED]

PENDING_STATUS = [OperationStatusEnum.PENDING]

FAILED_STATUS = [
    OperationStatusEnum.STARTED,
    OperationStatusEnum.REQUIRES_ACTION,
    OperationStatusEnum.FAILED,
]


def test_statusListsAreComplete() -> None:
    assert set(COMPLETED_STATUS + PENDING_STATUS + FAILED_STATUS) == set(OperationStatusEnum)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "result_status, payment_operation_status",
    [(OperationStatusEnum.COMPLETED, status) for status in COMPLETED_STATUS]
    + [(OperationStatusEnum.PENDING, status) for status in PENDING_STATUS]
    + [(OperationStatusEnum.FAILED, status) for status in FAILED_STATUS],
)
def test_givenAValidPaymentMethod_whenAfterConfirmingCompletes_thenPaymentFlowReturnsTheCorrectOperationResponse(
    fake_block: Type[protocols.AbstractBlock],
    fake_process_action_block: Type[protocols.AbstractBlock],
    result_status: OperationStatusEnum,
    payment_operation_status: OperationStatusEnum,
) -> None:
    # given a valid payment attempt
    db_payment_attempt = PaymentAttemptFactory.create()
    db_payment_method = PaymentMethodFactory.create(
        payment_attempt_id=db_payment_attempt.id,
        confirmable=True,
    )

    PaymentOperationFactory(
        type=OperationTypeEnum.INITIALIZE,
        status=OperationStatusEnum.STARTED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.INITIALIZE,
        status=OperationStatusEnum.COMPLETED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.PAY,
        status=OperationStatusEnum.STARTED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.PAY,
        status=OperationStatusEnum.COMPLETED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.AFTER_PAY,
        status=OperationStatusEnum.STARTED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.AFTER_PAY,
        status=OperationStatusEnum.COMPLETED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.CONFIRM,
        status=OperationStatusEnum.STARTED,
        payment_method_id=db_payment_method.id,
    ),
    PaymentOperationFactory(
        type=OperationTypeEnum.CONFIRM,
        status=OperationStatusEnum.COMPLETED,
        payment_method_id=db_payment_method.id,
    ),

    # when Confirming
    result = domain.PaymentFlow(
        repository=repositories.PaymentMethodRepository(),
        operations_repository=repositories.PaymentOperationRepository(),
        initialize_block=fake_block(
            fake_response_status=OperationStatusEnum.COMPLETED,
            fake_response_actions=[],
        ),
        process_action_block=fake_process_action_block(),
        pay_blocks=[],
        after_pay_blocks=[],
        confirm_blocks=[],
        after_confirm_blocks=[
            fake_block(
                fake_response_status=payment_operation_status,
            ),
        ],
    ).after_confirm(db_payment_method.to_domain())

    # then the payment flow returns the correct Operation Response
    assert models.PaymentOperation.objects.count() == 10
    db_payment_operations = models.PaymentOperation.objects.order_by("created_at").all()
    assert db_payment_operations[0].type == OperationTypeEnum.INITIALIZE
    assert db_payment_operations[0].status == OperationStatusEnum.STARTED

    assert db_payment_operations[1].type == OperationTypeEnum.INITIALIZE
    assert db_payment_operations[1].status == OperationStatusEnum.COMPLETED

    assert db_payment_operations[2].type == OperationTypeEnum.PAY
    assert db_payment_operations[2].status == OperationStatusEnum.STARTED

    assert db_payment_operations[3].type == OperationTypeEnum.PAY
    assert db_payment_operations[3].status == OperationStatusEnum.COMPLETED

    assert db_payment_operations[4].type == OperationTypeEnum.AFTER_PAY
    assert db_payment_operations[4].status == OperationStatusEnum.STARTED

    assert db_payment_operations[5].type == OperationTypeEnum.AFTER_PAY
    assert db_payment_operations[5].status == OperationStatusEnum.COMPLETED

    assert db_payment_operations[6].type == OperationTypeEnum.CONFIRM
    assert db_payment_operations[6].status == OperationStatusEnum.STARTED

    assert db_payment_operations[7].type == OperationTypeEnum.CONFIRM
    assert db_payment_operations[7].status == OperationStatusEnum.COMPLETED

    assert db_payment_operations[8].type == OperationTypeEnum.AFTER_CONFIRM
    assert db_payment_operations[8].status == OperationStatusEnum.STARTED

    assert db_payment_operations[9].type == OperationTypeEnum.AFTER_CONFIRM
    assert db_payment_operations[9].status == result_status

    assert result.type == OperationTypeEnum.AFTER_CONFIRM
    assert result.status == result_status
    assert result.actions == []
    assert result.payment_method.id == db_payment_method.id


@pytest.mark.django_db
def test_givenAPaymentMethodThatCannotAfterConfirm_whenAfterConfirming_thenPaymentFlowReturnsAFailedStatusOperationResponse(
    fake_block: Type[protocols.AbstractBlock],
    fake_process_action_block: Type[protocols.AbstractBlock],
) -> None:
    # Given a payment method that cannot initialize
    db_payment_attempt = PaymentAttemptFactory.create()
    db_payment_method = PaymentMethodFactory.create(
        payment_attempt_id=db_payment_attempt.id,
        confirmable=False,
    )
    assert dl.can_after_confirm(db_payment_method.to_domain()) is False

    # When Initializing
    result = domain.PaymentFlow(
        repository=repositories.PaymentMethodRepository(),
        operations_repository=repositories.PaymentOperationRepository(),
        initialize_block=fake_block(),
        process_action_block=fake_process_action_block(),
        pay_blocks=[],
        after_pay_blocks=[],
        confirm_blocks=[fake_block()],
        after_confirm_blocks=[],
    ).after_confirm(db_payment_method.to_domain())

    # then the payment flow returns a failed status operation response
    assert result.type == OperationTypeEnum.AFTER_CONFIRM
    assert result.status == OperationStatusEnum.FAILED
    result.error_message == "PaymentMethod cannot go through this operation"


@pytest.mark.django_db
def test_givenANonExistingPaymentMethod_whenAfterConfirming_thenPaymentFlowReturnsAFailedStatusOperationResponse(
    fake_block: Type[protocols.AbstractBlock], fake_process_action_block: Type[protocols.AbstractBlock]
) -> None:
    # Given a non existing payment method
    payment_method = domain.PaymentMethod(
        id=uuid4(),
        created_at=datetime.now(),
        payment_attempt_id=uuid4(),
        confirmable=False,
    )

    # When Confirming
    result = domain.PaymentFlow(
        repository=repositories.PaymentMethodRepository(),
        operations_repository=repositories.PaymentOperationRepository(),
        initialize_block=fake_block(),
        process_action_block=fake_process_action_block(),
        pay_blocks=[],
        after_pay_blocks=[],
        confirm_blocks=[],
        after_confirm_blocks=[],
    ).after_confirm(payment_method)

    # then the payment flow returns a failed status operation response
    assert result.type == OperationTypeEnum.AFTER_CONFIRM
    assert result.status == OperationStatusEnum.FAILED
    result.error_message == "PaymentMethod not found"
