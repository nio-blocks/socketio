import json
from ..socketio_block import SocketIO, SocketIOWebSocketClient
from nio.testing.block_test_case import NIOBlockTestCase
from nio.signal.base import Signal
from unittest.mock import MagicMock, patch


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
            'socketio_version': 'v0',
            'content': "{{$message}}",
            'log_level': 'DEBUG'
        })
        self._block.start()
        self._block.process_signals([Signal({"message": message})])

        socket_send_event.assert_called_once_with('pub', message)

        self._block.stop()

    def test_bogus_content_expr(self, socket_close, socket_connect,
                                socket_send_event):
        self.configure_block(self._block, {
            'socketio_version': 'v0',
            'content': '{{dict($message)}}',
            'log_level': 'DEBUG'
        })
        self._block.start()

        signals = [Signal({'message': 'foobar'})]
        self._block.process_signals(signals)

        self.assertFalse(socket_send_event.called)

    def test_default_expression(self, socket_close, socket_connect,
                                socket_send_event):
        self.configure_block(self._block, {
            'socketio_version': 'v0'
        })
        self._block.start()

        signal = Signal({'message': 'foobar'})
        self._block.process_signals([signal])
        socket_send_event.assert_called_with(
            'pub', json.dumps(signal.to_dict(), default=str))

    def test_management_signal(self, socket_close, socket_connect,
                               socket_send_event):
        """ Test that on failed connections the block notifies mgmt sigs """

        # Our connect method should connect first, then raise an exception
        socket_connect.side_effect = [True, Exception, Exception, Exception]
        self._block.notify_management_signal = MagicMock()

        # We want to not retry more than 2 seconds
        self.configure_block(self._block, {
            'socketio_version': 'v0',
            'content': '',
            'log_level': 'DEBUG',
            'retry_options': {'max_retry': 1}
        })
        self._block.start()
        # Force a reconnection that will retry once, then notify a management
        # signal
        self._block.handle_reconnect()
        # Should have an initial connection, a failed reconnect, then a retry
        self.assertEqual(socket_connect.call_count, 3)
        self.assertTrue(self._block.notify_management_signal.called)

    def test_subsequent_reconnects(self, close, conn, send):
        """ Tests that the reconnect handler can be called multiple times """

        self._block.notify_management_signal = MagicMock()

        # We want to not retry more than 2 seconds
        self.configure_block(self._block, {
            'socketio_version': 'v0',
            'content': '',
            'log_level': 'DEBUG'
        })
        self._block.start()

        # Make multiple handle reconnect calls
        self._block.handle_reconnect()
        self._block.handle_reconnect()

        # Make sure the block did not enter error state
        self.assertFalse(self._block.notify_management_signal.called)

    def test_no_send_after_stop(self, close, conn, send):
        """ Make sure signals sent after stop aren't sent """
        self.configure_block(self._block, {
            'socketio_version': 'v0'
        })

        # We expect one call to send when the block is started
        self._block.start()
        self._block.process_signals([Signal()])
        self.assertEqual(send.call_count, 1)

        # Now let's stop the block and make sure send didn't get called again
        # even if we send signals afterwards
        self._block.stop()
        self._block.process_signals([Signal()])
        self.assertEqual(send.call_count, 1)
