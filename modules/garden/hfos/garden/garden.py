"""


Module: Garden
==============

:copyright: (C) 2011-2016 riot@c-base.org
:license: GPLv3 (See LICENSE)

"""

from hfos.component import ConfigurableComponent
from hfos.logger import warn  # , hfoslog, error, critical

# from hfos.database import objectmodels
# from datetime import datetime
# from hfos.events.system import updatesubscriptions, send

__author__ = "Heiko 'riot' Weinen <riot@c-base.org>"


class Garden(ConfigurableComponent):
    """
    The Garden component checks on the existing garden watering rules and
    triggers pump start/stop events accordingly. It also accepts interrupt
    notifications from authorized users to start/stop/suspend the watering
    plan.
    In future, it should also monitor weather and sensor data to water
    efficiently.
    """
    channel = "hfosweb"

    configprops = {
    }

    def __init__(self, *args):
        """
        Initialize the Garden component.

        :param args:
        """

        super(Garden, self).__init__("GARDEN", *args)

        self.log("Started")

    def gardenrequest(self, event):
        self.log("Someone interacts with the garden! Yay!", event, lvl=warn)

    def objectcreation(self, event):
        if event.schema == 'wateringrule':
            self.log("Reloading rules")
            self._reloadWateringRules()

    def _reloadWateringRules(self):
        """
        Reloads all stored watering rules.
        """
        self.log("No, not yet.")
