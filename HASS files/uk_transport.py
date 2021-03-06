"""Support for UK public transport data provided by transportapi.com.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.uk_transport/
"""
import logging
import re
from datetime import datetime, timedelta

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import ATTR_ATTRIBUTION

from homeassistant.helpers.entity import Entity
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

CONF_API_APP_KEY = 'app_key'
CONF_API_APP_ID = 'app_id'
CONF_LIVE_BUS_TIME = 'live_bus_time'
CONF_LIVE_TRAIN_TIME = 'live_train_time'
CONF_STOP_ATCOCODE = 'stop_atcocode'
CONF_BUS_DIRECTION = 'direction'

# API codes for travel time details
ATTR_ATCOCODE = 'atcocode'
ATTR_LOCALITY = 'locality'
ATTR_STOP_NAME = 'stop_name'
ATTR_REQUEST_TIME = 'request_time'
ATTR_NEXT_BUSES = 'next_buses'
ATTRIBUTION = "Data provided by transportapi.com"

ATTR_STATION_CODE = 'station_code'
ATTR_DESTINATION_NAME = 'destination_name'
ATTR_NEXT_TRAINS = 'next_trains'

SCAN_INTERVAL = timedelta(minutes=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_APP_ID): cv.string,
    vol.Required(CONF_API_APP_KEY): cv.string,
    vol.Optional(CONF_LIVE_BUS_TIME): [{
        vol.Required(CONF_STOP_ATCOCODE): cv.string,
        vol.Required(CONF_BUS_DIRECTION): cv.string}],
    vol.Optional(CONF_LIVE_TRAIN_TIME): [{
        vol.Required(ATTR_STATION_CODE): cv.string,
        vol.Required(ATTR_DESTINATION_NAME): cv.string}]
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Get the uk_transport sensor."""
    sensors = []
    if config.get(CONF_LIVE_BUS_TIME):  # retunrs None if not present
        for live_bus_time in config.get(CONF_LIVE_BUS_TIME):           # trhows exception if not present
            stop_atcocode = live_bus_time.get(CONF_STOP_ATCOCODE)
            bus_direction = live_bus_time.get(CONF_BUS_DIRECTION)
            sensors.append(
                UkTransportLiveBusTimeSensor(
                    config.get(CONF_API_APP_ID),
                    config.get(CONF_API_APP_KEY),
                    stop_atcocode,
                    bus_direction))

    if config.get(CONF_LIVE_TRAIN_TIME):
        for live_train_time in config.get(CONF_LIVE_TRAIN_TIME):
            station_code = live_train_time.get(ATTR_STATION_CODE)
            destination_name = live_train_time.get(ATTR_DESTINATION_NAME)
            sensors.append(
                UkTransportLiveTrainTimeSensor(
                    config.get(CONF_API_APP_ID),
                    config.get(CONF_API_APP_KEY),
                    station_code,
                    destination_name))

    add_devices(sensors, True)


class UkTransportSensor(Entity):
    """
    Sensor that reads the UK transport web API.

    transportapi.com provides comprehensive transport data for UK train, tube
    and bus travel across the UK via simple JSON API. Subclasses of this
    base class can be used to access specific types of information.
    """

    TRANSPORT_API_URL_BASE = "https://transportapi.com/v3/uk/"
    ICON = 'mdi:car'

    def __init__(self, name, api_app_id, api_app_key, url):
        """Initialize the sensor."""
        self._data = {}
        self._api_app_id = api_app_id
        self._api_app_key = api_app_key
        self._url = self.TRANSPORT_API_URL_BASE + url
        self._name = name
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self.ICON

    def _do_api_request(self, params):
        """Perform an API request."""
        request_params = dict({
            'app_id': self._api_app_id,
            'app_key': self._api_app_key,
        }, **params)

        try:
            response = requests.get(self._url, params=request_params)
            response.raise_for_status()
            self._data = response.json()
        except requests.RequestException as req_exc:
            _LOGGER.warning(
                'Invalid response from transportapi.com: %s', req_exc
            )


class UkTransportLiveBusTimeSensor(UkTransportSensor):
    """Live bus time sensor from UK transportapi.com."""
    ICON = 'mdi:bus'

    def __init__(self, api_app_id, api_app_key, stop_atcocode, bus_direction):
        """Construct a live bus time sensor."""
        self._stop_atcocode = stop_atcocode
        self._bus_direction = bus_direction
        self._next_buses = []
        self._destination_re = re.compile(
            '{}'.format(bus_direction), re.IGNORECASE
        )

        sensor_name = 'Next bus to {}'.format(bus_direction)
        stop_url = 'bus/stop/{}/live.json'.format(stop_atcocode)

        UkTransportSensor.__init__(
            self, sensor_name, api_app_id, api_app_key, stop_url
        )

    def update(self):
        """Get the latest live departure data for the specified stop."""
        params = {'group': 'route', 'nextbuses': 'no'}

        self._do_api_request(params)

        if self._data != {}:
            self._next_buses = []

            for (route, departures) in self._data['departures'].items():
                for departure in departures:
                    if self._destination_re.search(departure['direction']):
                        self._next_buses.append({
                            'route': route,
                            'direction': departure['direction'],
                            'scheduled': departure['aimed_departure_time'],
                            'estimated': departure['best_departure_estimate']
                        })

            self._state = min(map(
                _delta_mins, [bus['scheduled'] for bus in self._next_buses]
            ))

    @property
    def device_state_attributes(self):
        """Return other details about the sensor state."""
        if self._data is not None:
            attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
            for key in [
                    ATTR_ATCOCODE, ATTR_LOCALITY, ATTR_STOP_NAME,
                    ATTR_REQUEST_TIME
            ]:
                attrs[key] = self._data.get(key)
            attrs[ATTR_NEXT_BUSES] = self._next_buses
            return attrs

    @property
    def unit_of_measurement(self):
        """Return the unit this state is expressed in."""
        return "min"

# As per bus but route becomes origin_name, direction becomes destination_name, next_suses becomes next_trains

class UkTransportLiveTrainTimeSensor(UkTransportSensor):
    """Live train time sensor from UK transportapi.com."""
    ICON = 'mdi:train'

    def __init__(self, api_app_id, api_app_key, station_code, destination_name):
        """Construct a live bus time sensor."""
        self._station_code = station_code         # stick to the naming convention of transportAPI
        self._destination_name = destination_name
        self._next_trains = {}

        sensor_name = 'Next train to {}'.format(destination_name)
        query_url =  'train/station/{}/live.json'.format(station_code)

        print(query_url)
        # also requires '&darwin=false&destination=WAT&train_status=passenger'

        UkTransportSensor.__init__(
            self, sensor_name, api_app_id, api_app_key, query_url
        )

    def update(self):
        """Get the latest live departure data for the specified stop."""
        params = {'darwin': 'false', 'destination': self._destination_name, 'train_status': 'passenger'}

        self._do_api_request(params)

        if self._data != {}:
            if 'error' in self._data:          # if query returns an error
                self._state = 'Error in query'
            else:
                self._next_trains = []
                for departure in self._data['departures']['all']:      # don't need a regex search as passing in destination to search
                    self._next_trains.append({
                        'origin_name': departure['origin_name'],
                        'destination_name': departure['destination_name'],
                        'status': departure['status'],
                        'scheduled': departure['aimed_departure_time'],
                        'estimated': departure['expected_departure_time'],
                        'platform': departure['platform'],
                        'operator_name': departure['operator_name']
                        })

                self._state = min(map(
                    _delta_mins, [train['scheduled'] for train in self._next_trains]
            ))

    @property
    def device_state_attributes(self):
        """Return other details about the sensor state."""
        if self._data is not None:
            attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}  # {'attribution': 'Data provided by transportapi.com'}
            for key in [
                    ATTR_STATION_CODE,
                    ATTR_DESTINATION_NAME
            ]:
                attrs[key] = self._data.get(key)           # place these attributes
            attrs[ATTR_NEXT_TRAINS] = self._next_trains
            return attrs

    @property
    def unit_of_measurement(self):
        """Return the unit this state is expressed in."""
        return "min"

def _delta_mins(hhmm_time_str):
    """Calculate time delta in minutes to a time in hh:mm format."""
    now = datetime.now()
    hhmm_time = datetime.strptime(hhmm_time_str, '%H:%M')

    hhmm_datetime = datetime(
        now.year, now.month, now.day,
        hour=hhmm_time.hour, minute=hhmm_time.minute
    )
    if hhmm_datetime < now:
        hhmm_datetime += timedelta(days=1)

    delta_mins = (hhmm_datetime - now).seconds // 60
    return delta_mins
