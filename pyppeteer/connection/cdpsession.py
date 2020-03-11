#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Connection/Session management module."""

import asyncio
import json
from typing import Awaitable, Dict, Union, TYPE_CHECKING

from pyppeteer.connection import Connection, createProtocolError, Message, rewriteError

try:
    from typing import TypedDict, TYPE_CHECKING
except ImportError:
    from typing_extensions import TypedDict

from pyee import AsyncIOEventEmitter

from pyppeteer.errors import NetworkError
from pyppeteer.events import Events

if TYPE_CHECKING:
    from typing import Optional


class CDPSession(AsyncIOEventEmitter):
    """Chrome Devtools Protocol Session.

    The :class:`CDPSession` instances are used to talk raw Chrome Devtools
    Protocol:

    * protocol methods can be called with :meth:`send` method.
    * protocol events can be subscribed to with :meth:`on` method.

    Documentation on DevTools Protocol can be found
    `here <https://chromedevtools.github.io/devtools-protocol/>`__.
    """

    def __init__(
            self,
            connection: Union[Connection, 'CDPSession'],
            targetType: str,
            sessionId: str,
            loop: asyncio.AbstractEventLoop,
    ) -> None:
        """Make new session."""
        super().__init__()
        self._callbacks: Dict[int, asyncio.Future] = {}
        self._connection: Optional[Connection] = connection
        self._targetType = targetType
        self._sessionId = sessionId
        self._loop = loop
        self._lastId = 0

    def send(self, method: str, params: dict = None) -> Awaitable:
        """Send message to the connected session.

        :arg str method: Protocol method name.
        :arg dict params: Optional method parameters.
        """
        if not self._connection:
            raise NetworkError(
                f'Protocol Error ({method}): Session closed. Most likely the ' f'{self._targetType} has been closed.'
            )
        self._lastId += 1
        id_ = self._lastId
        msg = {
            'id': id_,
            'method': method,
            'params': params or {},
        }
        return self._connection.send('Target.sendMessageToTarget', {
            'message': json.dumps(msg),
            'sessionId': self._sessionId,
        })

    def _onMessage(self, msg: Message) -> None:  # noqa: C901
        id_ = msg.get('id')
        callback = self._callbacks.get(id_)
        if id_ and id_ in self._callbacks:
            if msg.get('error'):
                callback.set_exception(
                    createProtocolError(
                        callback.error,  # type: ignore
                        callback.method,  # type: ignore
                        msg,
                    )
                )
            else:
                callback.set_result(msg.get('result'))
            del self._callbacks[id_]
        else:
            if msg.get('id'):
                raise ConnectionError(f'Received unexpected message with no callback: {msg}')
            import ipdb;ipdb.set_trace()
            self.emit(msg.get('method'), msg.get('params'))

    async def detach(self) -> None:
        """Detach session from target.

        Once detached, session won't emit any events and can't be used to send
        messages.
        """
        if not self._connection:
            raise NetworkError('Session already detached. Most likely' f'the {self._targetType} has been closed')
        await self._connection.send('Target.detachFromTarget', {'sessionId': self._sessionId})

    def _onClosed(self) -> None:
        for cb in self._callbacks.values():
            cb.set_exception(
                rewriteError(
                    cb.error,  # type: ignore
                    f'Protocol error {cb.method}: Target closed.',  # type: ignore
                )
            )
        self._callbacks.clear()
        self._connection = None
        self.emit(Events.CDPSession.Disconnected)

    def _createSession(self, targetType: str, sessionId: str) -> 'CDPSession':
        # TODO this is only used internally and is confusing with createSession
        session = CDPSession(self, targetType, sessionId, self._loop)
        self._sessions[sessionId] = session
        return session