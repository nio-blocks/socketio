SocketIO
========
Communicate with a Socket.IO server. Used to send data to a Socket.IO room and to read data from a Socket.IO room.

Properties
----------
- **connect_timeout**: How long to wait for the client to report that it is connected.
- **content**: Content to send to room. Should be json encoded.
- **host**: Socket.IO server location to connect to.
- **listen**: Whether or not the block should listen to messages from the SocketIo room.
- **port**: Socket.IO server port to connect to.
- **retry_options**: Options to configure how many attempts and how long to keep retrying to connect to socket room.
- **room**: Socket.IO room to connect to.
- **start_without_server**: Allow the service in which this block is running to start even if it is unable to connect to the client initially. The block will then try to reconnect given the retry strategy.

Inputs
------
- **default**: Signal to be sent as an event to the Socket.IO room.

Outputs
-------
- **default**: One signal for every event emitted from the Socket.IO room.

Commands
--------
- **reconnect_client**: Reconnect to a disconnected client.

Dependencies
------------
-   [requests](https://pypi.python.org/pypi/requests/)
-   [ws4py](https://pypi.python.org/pypi/ws4py)
