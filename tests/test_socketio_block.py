import json
from ..socketio_block import SocketIO, SocketIOWebSocketClient
from nio.util.support.block_test_case import NIOBlockTestCase
from nio.common.signal.base import Signal
from unittest.mock import MagicMock, patch, ANY


class MsgSignal(Signal):
    def __init__(self, message):
        super().__init__()
        self.message = message


@patch.object(SocketIOWebSocketClient, 'send_event')
@patch.object(SocketIOWebSocketClient, 'connect')
@patch.object(SocketIOWebSocketClient, 'close')
class TestSocketIO(NIOBlockTestCase):

    def setUp(self):
        super().setUp()
        self._block = SocketIO()
        self._block._do_handshake = MagicMock()

    def test_send(self, socket_close, socket_connect, socket_send_event):
        """Test that the block can send a signal."""
        message = 'hello_nio'
        self.configure_block(self._block, {
            'content': "{{$message}}",
            'log_level': 'DEBUG'
        })
        self._block.start()
        self._block.process_signals([MsgSignal(message)])

        socket_send_event.assert_called_once_with('pub', message)

        self._block.stop()

    def test_bogus_content_expr(self, socket_close, socket_connect,
                                socket_send_event):
        self.configure_block(self._block, {
            'content': '{{dict($message)}}',
            'log_level': 'DEBUG'
        })
        self._block.start()

        signals = [Signal({'message': 'foobar'})]
        self._block.process_signals(signals)
        with self.assertRaises(AssertionError):
            socket_send_event.assert_called_with('pub', ANY)

    def test_default_expression(self, socket_close, socket_connet,
                                socket_send_event):
        self.configure_block(self._block, {})
        self._block.start()

        signal = Signal({'message': 'foobar'})
        self._block.process_signals([signal])
        socket_send_event.assert_called_with('pub',
                                             json.dumps(signal.to_dict(),
                                                        default=str))
