import logging
import time

from ophyd.device import Component as Cmp, FormattedComponent as FCmp
from ophyd.pv_positioner import PVPositioner
from ophyd.signal import Signal, EpicsSignal, EpicsSignalRO

from .signal import AggregateSignal
from .inout import InOutPositioner

logger = logging.getLogger(__name__)
MAX_FILTERS = 12


class Filter(InOutPositioner):
    """
    A single attenuation blade, as implemented in the hard xray hutches.
    """
    state = Cmp(EpicsSignal, ':STATE', write_pv=':GO')
    thickness = Cmp(EpicsSignal, ':THICK')
    material = Cmp(EpicsSignal, ':MATERIAL')
    stuck = Cmp(EpicsSignal, ':STUCK')


class FeeFilter(InOutPositioner):
    """
    A single attenuation blade, as implemented in the FEE
    """
    state = Cmp(EpicsSignal, ':STATE', write_pv=':CMD')

    states_list = ['IN', 'OUT', 'FAIL']
    _invalid_states = ['FAIL']
    _unknown = 'XSTN'


class AttDoneSignal(AggregateSignal):
    """
    Signal that is 1 when all filters are done moving and 0 otherwise
    """
    def __init__(self, *, name, **kwargs):
        super().__init__(name=name, **kwargs)
        self._sub_signals = [f.state for f in self.parent.filters]

    def _calc_readback(self):
        for sig, state in self._cache.items():
            if state == sig._unknown:
                return 0
        return 1

    def put(self, *args, **kwargs):
        pass


class AttBase(PVPositioner):
    """
    Base class for the attenuators. Does not include filters, because the
    number of filters can vary.
    """
    # Positioner Signals
    setpoint = Cmp(EpicsSignal, ':R_DES')
    readback = Cmp(EpicsSignalRO, ':R_CUR')
    actuate = Cmp(EpicsSignal, ':GO')
    done = Cmp(AttDoneSignal)

    # Attenuator Signals
    energy = Cmp(EpicsSignalRO, ':T_CALC.VALE')
    trans_ceil = Cmp(EpicsSignalRO, ':R_CEIL')
    trans_floor = Cmp(EpicsSignalRO, ':R_FLOOR')
    user_energy = Cmp(EpicsSignal, ':EDES')
    eget_cmd = Cmp(EpicsSignal, ':EACT.SCAN')

    # Aux Signals
    status = Cmp(EpicsSignalRO, ':STATUS')
    calcpend = Cmp(EpicsSignalRO, ':CALCP')

    egu = ''  # Transmission is a unitless ratio
    _default_read_attrs = ['readback']

    def __init__(self, prefix, *, name, **kwargs):
        super().__init__(prefix, name=name, **kwargs)

        self.filters = []
        for i in range(1, MAX_FILTERS + 1):
            try:
                self.filters.append(getattr(self, 'filter{}'.format(i)))
            except AttributeError:
                break

    @property
    def actuate_value(self):
        """
        Sets the value we use in the GO command. This command will return 2 if
        the setpoint is closer to the ceiling than the floor, or 3 otherwise.
        In the unlikely event of a tie, we choose the floor.

        This will wait until a pending calculation completes before returning.
        """
        timeout = 1
        start = time.time()
        while self.calcpend.get() != 0:
            if time.time() - start > timeout:
                break
            time.sleep(0.01)

        goal = self.setpoint.get()
        ceil = self.trans_ceil.get()
        floor = self.trans_floor.get()
        if abs(goal - ceil) < abs(goal - floor):
            return 2
        else:
            return 3

    def set_energy(self, energy=None):
        """
        Sets the energy to use for transmission calculations.

        Parameters
        ----------
        energy: number, optional
            If provided, this is the energy we'll use for the transmission
            calcluations. If omitted, we'll clear any set energy and use the
            current beam energy instead.
        """
        if energy is None:
            logger.debug('Setting %s to use live energy', self.name or self)
            self.eget_cmd.put(6)
        else:
            logger.debug('Setting %s to use energy=%s',
                         self.name, energy)
            self.eget_cmd.put(0, use_complete=True)
            self.user_energy.put(energy)

    @property
    def transmission(self):
        """
        Ratio of pass-through beam to incoming beam. This is a value between
        1 (full beam) and 0 (no beam).
        """
        return self.position

    @property
    def inserted(self):
        """
        True if any blade is inserted
        """
        return self.position < 1

    @property
    def removed(self):
        """
        True if all blades are removed
        """
        return self.position == 1

    def insert(self):
        """
        Block the beam
        """
        return self.move(0)

    def remove(self):
        """
        Bring the attenuator fully out of the beam
        """
        return self.move(1)

    def stage(self):
        """
        Store the original positions of all filter blades
        This is better then storing and restoring the transmission because the
        mechanical state associated with a particular transmission changes with
        the beam energy.
        """
        for filt in self.filters:
            # If state is invalid, try to remove at end
            if filt.position in filt._invalid_states:
                self._original_vals[filt.state] = filt.out_states[0]
            # Otherwise, remember so we can restore
            else:
                self._original_vals[filt.state] = filt.state.value
        return super().stage()


class FeeAtt(AttBase):
    """
    Old attenuator IOC in the FEE.
    """
    setpoint = Cmp(EpicsSignal, ':RDES')
    readback = Cmp(EpicsSignal, ':RACT')
    energy = Cmp(EpicsSignalRO, 'ETOA.E')

    status = None
    calcpend = Cmp(Signal, value=0)

    # Hardcode filters for FEE, because there is only one.
    filter1 = FCmp(FeeFilter, '{self._filter_prefix}1')
    filter2 = FCmp(FeeFilter, '{self._filter_prefix}2')
    filter3 = FCmp(FeeFilter, '{self._filter_prefix}3')
    filter4 = FCmp(FeeFilter, '{self._filter_prefix}4')
    filter5 = FCmp(FeeFilter, '{self._filter_prefix}5')
    filter6 = FCmp(FeeFilter, '{self._filter_prefix}6')
    filter7 = FCmp(FeeFilter, '{self._filter_prefix}7')
    filter8 = FCmp(FeeFilter, '{self._filter_prefix}8')
    filter9 = FCmp(FeeFilter, '{self._filter_prefix}9')
    num_att = 9

    def __init__(self, prefix='SATT:FEE1:320', *, name='FeeAtt', **kwargs):
        self._filter_prefix = prefix[:-1]
        super().__init__(prefix, name=name, **kwargs)


def _make_att_classes(max_filters):
    att_classes = {}
    for i in range(1, max_filters + 1):
        att_filters = {}
        for n in range(1, i + 1):
            num = ':{:02}'.format(n)
            comp = FCmp(Filter, '{self._filter_prefix}' + num)
            att_filters['filter{}'.format(n)] = comp

        name = 'Attenuator{}'.format(i)
        cls = type(name, (AttBase,), att_filters)
        # Store the number of filters
        cls.num_att = i
        att_classes[i] = cls
    return att_classes


_att_classes = _make_att_classes(MAX_FILTERS)


def Attenuator(prefix, n_filters, *, name, **kwargs):
    """
    Factory function for instantiating an attenuator with the correct filter
    components given the number required.
    """
    return _att_classes[n_filters](prefix, name=name, **kwargs)
