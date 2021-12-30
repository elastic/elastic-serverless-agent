# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.

from abc import ABCMeta, abstractmethod
from typing import Any, TypeVar


class CommonShipper(metaclass=ABCMeta):
    """
    Abstract class for Shipper components
    """

    @abstractmethod
    def __init__(self, **kwargs: Any):
        raise NotImplementedError

    @abstractmethod
    def send(self, event: dict[str, Any]) -> Any:
        """
        Interface for sending the event by the shipper
        """

        raise NotImplementedError

    @abstractmethod
    def flush(self) -> None:
        """
        Interface for flushing the shipper
        """

        raise NotImplementedError


CommonShipperType = TypeVar("CommonShipperType", bound=CommonShipper)
