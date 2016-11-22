import logging

import aiohttp
from aiohttp import web

from . import api, plotting
from .state import State

log = logging.getLogger(__name__)


def broadcast(app, msg, exclude_client=None):
    s = msg.serialize()
    for ws in app['clients']:
        if ws != exclude_client:
            ws.send_str(s)


def notify_state(app, specific_client=None, exclude_client=None):
    state = app['state']
    num_paths = len(app['grouped_actions'])
    path_index = app['path_index']
    msg = api.StateMessage(
        state=state.name,
        num_paths=num_paths,
        path_index=path_index,
    )
    if specific_client:
        specific_client.send_str(msg.serialize())
    else:
        broadcast(app, msg, exclude_client=exclude_client)


def notify_new_document(app, exclude_client=None):
    msg = api.NewDocumentMessage(document=app['document'])
    broadcast(app, msg, exclude_client=exclude_client)


def notify_error(app, to_client, s):
    msg = api.ErrorMessage(s)
    to_client.send_str(msg.serialize())


def set_document(app, svgdoc):
    assert app['state'] == State.idle
    grouped_actions = plotting.process_upload(svgdoc)
    app['document'] = svgdoc
    app['grouped_actions'] = grouped_actions


async def handle_user_message(app, ws, msg):
    if isinstance(msg, api.SetDocumentMessage):
        assert app['state'] == State.idle
        try:
            set_document(app, msg.document)
        except Exception as e:
            notify_error(app, ws, str(e))
        else:
            notify_new_document(app, exclude_client=ws)
            notify_state(app)

    elif isinstance(msg, api.ManualPenUpMessage):
        assert app['state'] in (State.idle, State.paused)
        plotting.manual_pen_up(app)

    elif isinstance(msg, api.ManualPenDownMessage):
        assert app['state'] in (State.idle, State.paused)
        plotting.manual_pen_down(app)

    elif isinstance(msg, api.PausePlottingMessage):
        assert app['state'] == State.plotting
        plotting.pause(app)
        notify_state(app)

    elif isinstance(msg, api.ResumePlottingMessage):
        assert app['state'] in (State.idle, State.paused)
        plotting.resume(app)
        notify_state(app)

    elif isinstance(msg, api.CancelPlottingMessage):
        assert app['state'] in (State.plotting, State.paused)
        plotting.cancel(app)
        notify_state(app)

    else:
        log.error("Unknown user message: %s, ignoring.", msg)


async def client_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    app = request.app

    log.info("Client connected.")
    clients = app['clients']
    clients.add(ws)

    notify_state(app, specific_client=ws)

    try:
        async for raw_msg in ws:
            if raw_msg.tp == aiohttp.MsgType.text:
                msg = api.Message.deserialize(raw_msg.data)
                log.info("User message: %s", msg)
                await handle_user_message(app, ws, msg)
            elif raw_msg.tp == aiohttp.MsgType.closed:
                break
            elif raw_msg.tp == aiohttp.MsgType.error:
                log.info("User websocket error: %s", msg)
                break
            else:
                log.error("Unknown user message type: %s, ignoring.",
                          raw_msg.tp)
    finally:
        log.info("Client connection closed.")
        clients.remove(ws)

    return ws
