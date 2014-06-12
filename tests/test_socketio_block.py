from socketio.socketio_block import SocketIO, SocketIOWebSocketClient
from nio.util.support.block_test_case import NIOBlockTestCase
from nio.common.signal.base import Signal
from unittest.mock import MagicMock, patch


@patch('socketio.socketio_block.SocketIOWebSocketClient.send_event')
@patch('socketio.socketio_block.SocketIOWebSocketClient.connect')
@patch('socketio.socketio_block.SocketIOWebSocketClient.close')
class TestSocketIO(NIOBlockTestCase):

    def setUp(self):
        super().setUp()
        self._block = SocketIO()
        self._block._do_handshake = MagicMock()

    def test_send(self, socket_close, socket_connect, socket_send_event):
        """Test that the block can send a signal."""
        message = 'hello_nio'
        self.configure_block(self._block, {
            'content': '"{0}"'.format(message),
            'log_level': 'DEBUG'
        })
        self._block.start()
        self._block.process_signals([Signal()])

        socket_send_event.assert_called_once_with('pub', message)

        self._block.stop()
