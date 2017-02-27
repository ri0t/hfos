"""py.test config"""

import pytest

import sys
import threading
import collections
from time import sleep
from collections import deque

from circuits.core.manager import TIMEOUT
from circuits import handler, BaseComponent, Debugger, Manager


class Watcher(BaseComponent):

    def init(self):
        self._lock = threading.Lock()
        self.events = deque()

    @handler(channel="*", priority=999.9)
    def _on_event(self, event, *args, **kwargs):
        with self._lock:
            self.events.append(event)

    def clear(self):
        self.events.clear()

    def wait(self, name, channel=None, timeout=6.0):
        for i in range(int(timeout / TIMEOUT)):
            with self._lock:
                for event in self.events:
                    if event.name == name and event.waitingHandlers == 0:
                        if (channel is None) or (channel in event.channels):
                            return True
            sleep(TIMEOUT)
        else:
            return False


class Flag(object):
    status = False
    event = None


def call_event_from_name(manager, event, event_name, *channels):
    fired = False
    value = None
    for r in manager.waitEvent(event_name):
        if not fired:
            fired = True
            value = manager.fire(event, *channels)
        sleep(0.1)
    return value


def call_event(manager, event, *channels):
    return call_event_from_name(manager, event, event.name, *channels)


class WaitEvent(object):

    def __init__(self, manager, name, channel=None, timeout=6.0):
        if channel is None:
            channel = getattr(manager, "channel", None)

        self.timeout = timeout
        self.manager = manager

        flag = Flag()

        @handler(name, channel=channel)
        def on_event(self, event):
            flag.status = True
            flag.event = event

        self.handler = self.manager.addHandler(on_event)
        self.flag = flag

    def wait(self):
        try:
            for i in range(int(self.timeout / TIMEOUT)):
                if self.flag.status:
                    return self.flag.event
                sleep(TIMEOUT)
        finally:
            self.manager.removeHandler(self.handler)


def wait_for(obj, attr, value=True, timeout=3.0):
    from circuits.core.manager import TIMEOUT
    for i in range(int(timeout / TIMEOUT)):
        if isinstance(value, collections.Callable):
            if value(obj, attr):
                return True
        elif getattr(obj, attr) == value:
            return True
        sleep(TIMEOUT)


@pytest.fixture
def manager(request):
    manager = Manager()

    def finalizer():
        manager.stop()

    request.addfinalizer(finalizer)

    waiter = WaitEvent(manager, "started")
    manager.start()
    assert waiter.wait()

    if request.config.option.verbose:
        verbose = True
    else:
        verbose = False

    Debugger(events=verbose).register(manager)

    return manager


@pytest.fixture
def watcher(request, manager):
    watcher = Watcher().register(manager)

    def finalizer():
        waiter = WaitEvent(manager, "unregistered")
        watcher.unregister()
        waiter.wait()

    request.addfinalizer(finalizer)

    return watcher


def pytest_namespace():
    return dict((
        ("WaitEvent", WaitEvent),
        ("wait_for", wait_for),
        ("call_event", call_event),
        ("PLATFORM", sys.platform),
        ("PYVER", sys.version_info[:3]),
        ("call_event_from_name", call_event_from_name),
    ))