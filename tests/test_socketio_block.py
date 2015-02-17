import json
from ..socketio_block import SocketIO, SocketIOWebSocketClient
from nio.util.support.block_test_case import NIOBlockTestCase
from nio.common.signal.base import Signal
from time import sleep
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

    def test_default_expression(self, socket_close, socket_connect,
                                socket_send_event):
        self.configure_block(self._block, {})
        self._block.start()

        signal = Signal({'message': 'foobar'})
        self._block.process_signals([signal])
        socket_send_event.assert_called_with('pub',
                                             json.dumps(signal.to_dict(),
                                                        default=str))

    def test_management_signal(self, socket_close, socket_connect,
                               socket_send_event):
        """ Test that on failed connections the block notifies mgmt sigs """

        # Our connect method should raise an exception
        socket_connect.side_effect = Exception("Fake Connection Failed")
        self._block.notify_management_signal = MagicMock()

        # We want to not retry more than 2 seconds
        self.configure_block(self._block, {
            'content': '',
            'log_level': 'DEBUG',
            'max_retry': {'seconds': 2}
        })
        self._block.start()

        # Wait one second and make sure we haven't notified management signals
        sleep(1)
        self.assertFalse(self._block.notify_management_signal.called)

        # Wait one more second and make sure we did notify the error
        sleep(1.1)
        self.assertTrue(self._block.notify_management_signal.called)

    def test_subsequent_reconnects(self, close, conn, send):
        """ Tests that the reconnect handler can be called multiple times """

        self._block.notify_management_signal = MagicMock()

        # We want to not retry more than 2 seconds
        self.configure_block(self._block, {
            'content': '',
            'log_level': 'DEBUG',
            'max_retry': {'seconds': 20}
        })
        self._block.start()

        # Make multiple handle reconnect calls
        self._block.handle_reconnect()
        self._block.handle_reconnect()

        # Make sure the block did not enter error state
        self.assertFalse(self._block.notify_management_signal.called)

        # Make sure our reconnection job is scheduled
        self.assertIsNotNone(self._block._connection_job)
