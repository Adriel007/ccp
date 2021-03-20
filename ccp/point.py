from copy import copy
from warnings import warn

import numpy as np
import toml
import plotly.graph_objects as go
from scipy.optimize import newton

from ccp import check_units, State, Q_
from ccp.config.utilities import r_getattr


class Point:
    @check_units
    def __init__(
        self,
        suc=None,
        disch=None,
        flow_v=None,
        flow_m=None,
        speed=None,
        head=None,
        eff=None,
        power=None,
        phi=None,
        psi=None,
        volume_ratio=None,
        b=None,
        D=None,
    ):
        """Point.
        A point in the compressor map that can be defined in different ways.

        Parameters
        ----------
        speed : float
            Speed in 1/s.
        flow_v or flow_m : float
            Volumetric or mass flow.
        suc, disch : ccp.State, ccp.State
            Suction and discharge states for the point.
        suc, head, eff : ccp.State, float, float
            Suction state, polytropic head and polytropic efficiency.
        suc, head, power : ccp.State, float, float
            Suction state, polytropic head and gas power.
        suc, eff, volume_ratio : ccp.State, float, float
            Suction state, polytropic efficiency and volume ratio.
        b, D : pint.Quantity, float, optional
            Impeller width and diameter.
            This is optional, if not provided it will be set when the point is
            assigned to an impeller.


        Returns
        -------
        Point : ccp.Point
            A point in the compressor map.
        """
        self.suc = suc
        self.disch = disch
        self.flow_v = flow_v
        self.flow_m = flow_m
        self.speed = speed
        self.head = head
        self.eff = eff
        self.power = power

        self.phi = phi
        self.psi = psi
        self.volume_ratio = volume_ratio

        self.b = b
        self.D = D

        # dummy state used to avoid copying states
        self._dummy_state = copy(self.suc)

        kwargs_list = []

        for k in [
            "suc",
            "disch",
            "flow_v",
            "flow_m",
            "speed",
            "head",
            "eff",
            "power",
            "phi",
            "psi",
            "volume_ratio",
        ]:
            if getattr(self, k):
                kwargs_list.append(k)

        kwargs_str = "_".join(sorted(kwargs_list))

        # calc_options = {
        #     "disch_flow_v_speed_suc": self._calc_fro,
        #     "eff-suc-volume_ratio": self._calc_from_eff_suc_volume_ratio,
        #     "eff-head-suc": self._calc_from_eff_head_suc,
        # }
        # calc_options[kwargs_str]()
        getattr(self, '_calc_from_' + kwargs_str)()

        self.phi_ratio = 1.0
        self.psi_ratio = 1.0
        self.reynolds_ratio = 1.0
        # mach in the ptc 10 is compared with Mmt - Mmsp
        self.mach_diff = 0.0
        # ratio between specific volume ratios in original and converted conditions
        self.volume_ratio_ratio = 1.0

        self._add_point_plot()

    def _u(self):
        """Impeller tip speed."""
        speed = self.speed

        u = speed * self.D / 2

        return u

    def _phi(self):
        """Flow coefficient."""
        flow_v = self.flow_v

        u = self._u()

        phi = flow_v * 4 / (np.pi * self.D ** 2 * u)

        return phi.to("dimensionless")

    def _psi(self):
        """Head coefficient."""
        head = self.head

        u = self._u()

        psi = 2 * head / u ** 2

        return psi.to("dimensionless")

    def _mach(self):
        """Mach number."""
        suc = self.suc

        u = self._u()
        a = suc.speed_sound()

        mach = u / a

        return mach.to("dimensionless")

    def _reynolds(self):
        """Reynolds number."""
        suc = self.suc

        u = self._u()
        b = self.b
        v = suc.viscosity() / suc.rho()

        reynolds = u * b / v

        return reynolds.to("dimensionless")

    def _u_from_psi(self):
        psi = self.psi
        head = self.head

        u = np.sqrt(2 * head / psi)

        return u.to("m/s")

    def _speed_from_psi(self):
        D = self.D
        u = self._u_from_psi()

        speed = 2 * u / D

        return speed.to("rad/s")

    def _flow_from_phi(self, D=None):
        # TODO get flow for point generated from suc-eff-volume_ratio
        phi = self.phi
        if D is None:
            D = self.D
        u = self._u_from_psi()

        flow_v = phi * (np.pi * D ** 2 * u) / 4

        return flow_v

    @classmethod
    def convert_from(
        cls, original_point, suc=None, volume_ratio=None, speed=None, D=None
    ):
        """Convert point from an original point.

        The user must provide 3 of the 4 available arguments. The argument which is not
        provided will be calculated.
        """

        if volume_ratio is None:
            flow_v = flow_from_phi(D=D, phi=original_point.phi, speed=speed)
            head = head_from_psi(D=D, psi=original_point.psi, speed=speed)
            converted_point = cls(
                suc=suc,
                eff=original_point.eff,
                head=head,
                flow_v=flow_v,
                speed=speed,
                b=original_point.b,
                D=D,
            )

        # TODO Implement speed and D as None
        if speed is None:
            pass
        if D is None:
            pass

        converted_point.phi_ratio = converted_point.phi / original_point.phi
        converted_point.psi_ratio = converted_point.psi / original_point.psi
        converted_point.reynolds_ratio = (
            converted_point.reynolds / original_point.reynolds
        )
        converted_point.mach_diff = converted_point.mach - original_point.mach
        converted_point.volume_ratio_ratio = (
            converted_point.volume_ratio / original_point.volume_ratio
        )

        return converted_point

    def _add_point_plot(self):
        """Add plot to point after point is fully defined."""
        for state in ["suc", "disch"]:
            for attr in ["p", "T"]:
                plot = plot_func(self, ".".join([state, attr]))
                setattr(getattr(self, state), attr + "_plot", plot)
        for attr in ["head", "eff", "power"]:
            plot = plot_func(self, attr)
            setattr(self, attr + "_plot", plot)

    def __str__(self):
        return (
            f"\nPoint: "
            f"\nVolume flow: {self.flow_v:.2f~P}"
            f"\nHead: {self.head:.2f~P}"
            f"\nEfficiency: {self.eff:.2f~P}"
            f"\nPower: {self.power:.2f~P}"
        )

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            if (
                self.suc == other.suc
                and np.allclose(self.speed, other.speed)
                and np.allclose(self.flow_v, other.flow_v)
                and np.allclose(self.head, other.head)
                and np.allclose(self.eff, other.eff)
            ):
                return True

        return False

    def __repr__(self):

        return (
            f"{self.__class__.__name__}(suc={self.suc},"
            f' speed=Q_("{self.speed:.0f~P}"),'
            f' flow_v=Q_("{self.flow_v:.2f~P}"),'
            f' head=Q_("{self.head:.0f~P}"),'
            f' eff=Q_("{self.eff:.3f~P}"))'
        )

    def _calc_from_disch_flow_v_speed_suc(self):
        self.head = head_pol_schultz(self.suc, self.disch)
        self.eff = eff_pol_schultz(self.suc, self.disch)
        self.volume_ratio = self.suc.v() / self.disch.v()
        self.flow_m = self.suc.rho() * self.flow_v
        self.power = power_calc(self.flow_m, self.head, self.eff)
        self.phi = phi(self.flow_v, self.speed, self.D)
        self.psi = psi(self.head, self.speed, self.D)

    def _calc_from_eff_suc_volume_ratio(self):
        eff = self.eff
        suc = self.suc
        volume_ratio = self.volume_ratio

        disch_v = suc.v() / volume_ratio
        disch_rho = 1 / disch_v

        #  consider first an isentropic compression
        disch = State.define(rho=disch_rho, s=suc.s(), fluid=suc.fluid)

        def update_state(x, update_type):
            if update_type == "pressure":
                disch.update(rho=disch_rho, p=x)
            elif update_type == "temperature":
                disch.update(rho=disch_rho, T=x)
            new_eff = self._eff_pol_schultz(disch=disch)
            if not 0.0 < new_eff < 1.1:
                raise ValueError

            return (new_eff - eff).magnitude

        try:
            newton(update_state, disch.T().magnitude, args=("temperature",), tol=1e-1)
        except ValueError:
            # re-instantiate disch, since update with temperature not converging
            # might break the state
            disch = State.define(rho=disch_rho, s=suc.s(), fluid=suc.fluid)
            newton(update_state, disch.p().magnitude, args=("pressure",), tol=1e-1)

        self.disch = disch
        self.head = head_pol_schultz(suc, disch)

    def _calc_from_eff_head_suc(self):
        eff = self.eff
        head = self.head
        suc = self.suc

        h_disch = head / eff + suc.h()

        #  consider first an isentropic compression
        disch = State.define(h=h_disch, s=suc.s(), fluid=suc.fluid)

        def update_pressure(p):
            disch.update(h=h_disch, p=p)
            new_head = self._head_pol_schultz(disch)

            return (new_head - head).magnitude

        newton(update_pressure, disch.p().magnitude, tol=1e-1)

        self.disch = disch
        self.volume_ratio = self._volume_ratio()
        self.power = self._power_calc()

    def _head_pol_schultz(self, disch=None):
        """Polytropic head corrected by the Schultz factor."""
        if disch is None:
            disch = self.disch

        f = self._schultz_f(disch=disch)
        head = self._head_pol(disch=disch)

        return f * head

    def _head_pol_mallen_saville(self, disch=None):
        """Polytropic head as per Mallen-Saville"""
        if disch is None:
            disch = self.disch

        suc = self.suc

        head = (disch.h() - suc.h()) - (disch.s() - suc.s()) * (
            disch.T() - suc.T()
        ) / np.log(disch.T() / suc.T())

        return head

    def _head_reference(self, disch=None):
        """Reference head as described by Huntington (1985).

        It consists of two loops.
        One converges the T1 temperature at each step by evaluating the
        diffence between H = vm * delta_p and H = eff * delta_h.
        The other evaluates the efficiency by checking the difference between
        the last T1 to the discharge temperature Td.

        Results are stored at self._ref_eff, self._ref_H and self._ref_n.
        self._ref_n is a list with n_exp at each step for the final converged
        efficiency.

        """
        if disch is None:
            disch = self.disch

        suc = self.suc

        def calc_step_discharge_temp(T1, T0, self, p1, e):
            s0 = State.define(p=self, T=T0, fluid=suc.fluid)
            s1 = State.define(p=p1, T=T1, fluid=suc.fluid)
            h0 = s0.h()
            h1 = s1.h()

            vm = ((1 / s0.rho()) + (1 / s1.rho())) / 2
            delta_p = Q_(p1 - self, "Pa")
            H0 = vm * delta_p
            H1 = e * (h1 - h0)

            return (H1 - H0).magnitude

        def calc_eff(e, suc, disch):
            p_intervals = np.linspace(suc.p(), disch.p(), 1000)

            T0 = suc.T().magnitude

            self._ref_H = 0
            self._ref_n = []

            for self, p1 in zip(p_intervals[:-1], p_intervals[1:]):
                T1 = newton(
                    calc_step_discharge_temp, (T0 + 1e-3), args=(T0, self, p1, e)
                )

                s0 = State.define(p=self, T=T0, fluid=suc.fluid)
                s1 = State.define(p=p1, T=T1, fluid=suc.fluid)
                step_point = Point(flow_m=1, speed=1, suc=s0, disch=s1)

                self._ref_H += step_point._head_pol()
                self._ref_n.append(step_point._n_exp())
                T0 = T1

            return disch.T().magnitude - T1

        self._ref_eff = newton(calc_eff, 0.8, args=(suc, disch))

    def _schultz_f(self, disch=None):
        """Schultz factor."""
        suc = self.suc
        if disch is None:
            disch = self.disch

        # define state to isentropic discharge using dummy state
        disch_s = self._dummy_state
        disch_s.update(p=disch.p(), s=suc.s())

        h2s_h1 = disch_s.h() - suc.h()
        h_isen = self._head_isen(disch=disch)

        return h2s_h1 / h_isen

    def _head_isen(self, disch=None):
        """Isentropic head."""
        suc = self.suc
        if disch is None:
            disch = self.disch

        # define state to isentropic discharge using dummy state
        disch_s = self._dummy_state
        disch_s.update(p=disch.p(), s=suc.s())

        return self._head_pol(disch=disch_s).to("joule/kilogram")

    def _eff_isen(self):
        """Isentropic efficiency."""
        suc = self.suc
        disch = self.disch

        ws = self._head_isen()
        dh = disch.h() - suc.h()
        return ws / dh

    def _head_pol(self, disch=None):
        """Polytropic head."""
        suc = self.suc

        if disch is None:
            disch = self.disch

        n = self._n_exp(disch=disch)

        p2 = disch.p()
        v2 = 1 / disch.rho()
        p1 = suc.p()
        v1 = 1 / suc.rho()

        return (n / (n - 1)) * (p2 * v2 - p1 * v1).to("joule/kilogram")

    def _eff_pol(self):
        """Polytropic efficiency."""
        suc = self.suc
        disch = self.disch

        wp = self._head_pol()

        dh = disch.h() - suc.h()

        return wp / dh

    def _n_exp(self, disch=None):
        """Polytropic exponent."""
        suc = self.suc

        if disch is None:
            disch = self.disch

        ps = suc.p()
        vs = 1 / suc.rho()
        pd = disch.p()
        vd = 1 / disch.rho()

        return np.log(pd / ps) / np.log(vs / vd)

    def _eff_pol_schultz(self, disch=None):
        """Schultz polytropic efficiency."""
        suc = self.suc
        if disch is None:
            disch = self.disch

        wp = self._head_pol_schultz(disch=disch)
        dh = disch.h() - suc.h()

        return wp / dh

    def _power_calc(self):
        """Power."""
        flow_m = self.flow_m
        head = self.head
        eff = self.eff

        return (flow_m * head / eff).to("watt")

    def _volume_ratio(self):
        suc = self.suc
        disch = self.disch

        vs = 1 / suc.rho()
        vd = 1 / disch.rho()

        return vd / vs

    def _dict_to_save(self):
        """Returns a dict that will be saved to a toml file."""
        return dict(
            p=str(self.suc.p()),
            T=str(self.suc.T()),
            fluid=self.suc.fluid,
            speed=str(self.speed),
            flow_v=str(self.flow_v),
            head=str(self.head),
            eff=str(self.eff),
        )

    @staticmethod
    def _dict_from_load(dict_parameters):
        """Change dict to format that can be used by load constructor."""
        suc = State.define(
            p=Q_(dict_parameters.pop("p")),
            T=Q_(dict_parameters.pop("T")),
            fluid=dict_parameters.pop("fluid"),
        )

        return dict(suc=suc, **{k: Q_(v) for k, v in dict_parameters.items()})

    def save(self, file_name):
        """Save point to toml file."""
        with open(file_name, mode="w") as f:
            toml.dump(self._dict_to_save(), f)

    @classmethod
    def load(cls, file_name):
        """Load point from toml file."""
        with open(file_name) as f:
            parameters = toml.load(f)

        return cls(**cls._dict_from_load(parameters))


def plot_func(self, attr):
    def inner(*args, plot_kws=None, **kwargs):
        """Plot parameter versus volumetric flow.

        You can choose units with the arguments x_units='...' and
        y_units='...'.
        """
        fig = kwargs.pop("fig", None)

        if fig is None:
            fig = go.Figure()

        if plot_kws is None:
            plot_kws = {}

        x_units = kwargs.get("flow_v_units", None)
        y_units = kwargs.get(f"{attr}_units", None)
        name = kwargs.get("name", None)

        point_attr = r_getattr(self, attr)
        if callable(point_attr):
            point_attr = point_attr()

        if y_units is not None:
            point_attr = point_attr.to(y_units)

        value = getattr(point_attr, "magnitude")
        units = getattr(point_attr, "units")

        flow_v = self.flow_v

        if x_units is not None:
            flow_v = flow_v.to(x_units)

        fig.add_trace(go.Scatter(x=[flow_v], y=[value], name=name, **plot_kws))

        return fig

    return inner


def n_exp(suc, disch):
    """Polytropic exponent.

    Parameters
    ----------
    suc : ccp.State
        Suction state.
    disch : ccp.State
        Discharge state.

    Returns
    -------
    n_exp : float
        Polytropic exponent.
    """
    ps = suc.p()
    vs = 1 / suc.rho()
    pd = disch.p()
    vd = 1 / disch.rho()

    return np.log(pd / ps) / np.log(vs / vd)


def head_polytropic(suc, disch):
    """Polytropic head.

    Parameters
    ----------
    suc : ccp.State
        Suction state.
    disch : ccp.State
        Discharge state.

    Returns
    -------
    head_polytropic : pint.Quantity
        Polytropic head (J/kg).
    """

    n = n_exp(suc, disch)

    p2 = disch.p()
    v2 = 1 / disch.rho()
    p1 = suc.p()
    v1 = 1 / suc.rho()

    return (n / (n - 1)) * (p2 * v2 - p1 * v1).to("joule/kilogram")


def head_isen(suc, disch):
    """Isentropic head.
    Parameters
    ----------
    suc : ccp.State
        Suction state.
    disch : ccp.State
        Discharge state.

    Returns
    -------
    head_isen : pint.Quantity
        Isentropic head.
    """
    # define state to isentropic discharge using dummy state
    disch_s = copy(disch)
    disch_s.update(p=disch.p(), s=suc.s())

    return head_polytropic(suc, disch_s).to("joule/kilogram")


def schultz_f(suc, disch):
    """Schultz factor.

    Parameters
    ----------
    suc : ccp.State
        Suction state.
    disch : ccp.State
        Discharge state.

    Returns
    -------
    schultz_f : float
        Schultz polytropic factor.
    """

    # define state to isentropic discharge using dummy state
    disch_s = copy(disch)
    disch_s.update(p=disch.p(), s=suc.s())

    h2s_h1 = disch_s.h() - suc.h()
    h_isen = head_isen(suc, disch)

    return h2s_h1 / h_isen


def head_pol_schultz(suc, disch):
    """Polytropic head corrected by the Schultz factor.

    Parameters
    ----------
    suc : ccp.State
        Suction state.
    disch : ccp.State
        Discharge state.

    Returns
    -------
    head_pol_schultz : pint.Quantity
        Schultz polytropic head (J/kg).
    """

    f = schultz_f(suc, disch)
    head = head_polytropic(suc, disch)

    return f * head


def eff_pol_schultz(suc, disch):
    """Schultz polytropic efficiency.
        Parameters
    ----------
    suc : ccp.State
        Suction state.
    disch : ccp.State
        Discharge state.

    Returns
    -------
    head_pol_schultz : pint.Quantity
        Schultz polytropic efficiency (dimensionless).
    """
    wp = head_pol_schultz(suc, disch)
    dh = disch.h() - suc.h()

    return (wp / dh).to("dimensionless")


@check_units
def power_calc(flow_m, head, eff):
    """Calculate power.

    Parameters
    ----------
    flow_m : pint.Quantity, float
        Mass flow (kg/s).
    head : pint.Quantity, float
        Head (J/kg).
    eff : pint.Quantity, float
        Efficiency (dimensionless).

    Returns
    -------
    power : pint.Quantity
        Power (watt).
    """
    power = flow_m * head / eff

    return power.to("watt")


@check_units
def u_calc(D, speed):
    """Calculate the impeller tip speed.

    Parameters
    ----------
    D : pint.Quantity, float
        Impeller diameter (m).
    speed : pint.Quantity, float
        Impeller speed (rad/s).

    Returns
    -------
    u_calc : pint.Quantity
        Impeller tip speed (m/s).
    """
    u = speed * D / 2
    return u.to("m/s")


@check_units
def psi(head, speed, D):
    """Polytropic head coefficient.

    Parameters
    ----------
    head : pint.Quantity, float
        Polytropic head (J/kg).
    speed : pint.Quantity, float
        Impeller speed (rad/s).
    D : pint.Quantity, float
        Impeller diameter.

    Returns
    -------
    psi : pint.Quantity
        Polytropic head coefficient (dimensionless).
    """
    u = u_calc(D, speed)
    psi = head / (u ** 2 / 2)
    return psi.to("dimensionless")


@check_units
def u_from_psi(head, psi):
    """Calculate u_calc from non dimensional psi.

    Parameters
    ----------
    head : pint.Quantity, float
        Polytropic head.
    psi : pint.Quantity, float
        Head coefficient.

    Returns
    -------
    u_calc : pint.Quantity, float
        Impeller tip speed.
    """
    u = np.sqrt(2 * head / psi)

    return u.to("m/s")


@check_units
def speed_from_psi(D, head, psi):
    """Calculate speed from non dimensional psi.

    Parameters
    ----------
    D : pint.Quantity, float
        Impeller diameter.
    head : pint.Quantity, float
        Polytropic head.
    psi : pint.Quantity, float
        Head coefficient.

    Returns
    -------
    u_calc : pint.Quantity, float
        Impeller tip speed.
    """
    u = u_from_psi(head, psi)

    speed = 2 * u / D

    return speed.to("rad/s")


@check_units
def phi(flow_v, speed, D):
    """Flow coefficient."""
    u = u_calc(D, speed)

    phi = flow_v * 4 / (np.pi * D ** 2 * u)

    return phi.to("dimensionless")


@check_units
def flow_from_phi(D, phi, speed):
    """Calculate flow from non dimensional phi.

    Parameters
    ----------
    D : pint.Quantity, float
        Impeller diameter (m).
    phi : pint.Quantity, float
        Flow coefficient (m³/s).
    speed : pint.Quantity, float
        Speed (rad/s).

    Returns
    -------
    u_calc : pint.Quantity, float
        Impeller tip speed.
    """
    u = speed * D / 2

    flow_v = phi * (np.pi * D ** 2 * u) / 4

    return flow_v.to("m**3/s")


def head_from_psi(D, psi, speed):
    """Calculate head from non dimensional psi.

    Parameters
    ----------
    D : pint.Quantity, float
        Impeller diameter (m).
    psi : pint.Quantity, float
        Head coefficient.
    speed : pint.Quantity, float
        Speed (rad/s).
    Returns
    -------
    u_calc : pint.Quantity, float
        Impeller tip speed.
    """
    u = speed * D / 2
    head = psi * (u ** 2 / 2)

    return head.to("J/kg")
