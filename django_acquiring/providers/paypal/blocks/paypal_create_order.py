import uuid
from dataclasses import dataclass
from typing import Sequence

from django_acquiring.domain import BlockResponse, wrapped_by_block_events
from django_acquiring.enums import OperationStatusEnum
from django_acquiring.protocols import AbstractBlock, AbstractBlockResponse, AbstractPaymentMethod

from ..adapter import PayPalAdapter
from ..domain import Order, OrderIntentEnum, PayPalStatusEnum


@dataclass
class PayPalCreateOrder:
    adapter: PayPalAdapter

    @wrapped_by_block_events
    def run(self, payment_method: AbstractPaymentMethod, *args: Sequence, **kwargs: dict) -> AbstractBlockResponse:
        transaction_id = uuid.uuid4()
        order = Order(
            intent=OrderIntentEnum.CAPTURE,
            purchase_units=[],
        )
        response = self.adapter.create_order(
            request_id=transaction_id,
            order=order,
        )

        if response.status == PayPalStatusEnum.FAILED:
            return BlockResponse(
                status=OperationStatusEnum.FAILED,
                actions=[],
                error_message=str(response.unparsed_data),
            )

        parsed_data = self._parse_response_data(response.unparsed_data)

        return BlockResponse(
            status=OperationStatusEnum.COMPLETED,
            actions=[{"redirect_url": parsed_data["redirect_url"]}],  # TODO Convert Action to dataclass
        )

    def _parse_response_data(self, data: dict) -> dict:
        return {"redirect_url": next((link["href"] for link in data["links"] if link["rel"] == "approve"))}


assert issubclass(PayPalCreateOrder, AbstractBlock)
