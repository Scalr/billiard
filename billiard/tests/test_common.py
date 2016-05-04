from __future__ import absolute_import

import os
import signal

from contextlib import contextmanager
from time import time, sleep

from billiard.common import (
    _shutdown_cleanup,
    reset_signals,
    restart_state,
)

from billiard.pool import (
    Pool,
    SoftTimeLimitExceeded,
    TimeLimitExceeded,
)

from .case import Case, Mock, call, patch, skip


def signo(name):
    return getattr(signal, name)


@contextmanager
def termsigs(default, full):
    from billiard import common
    prev_def, common.TERMSIGS_DEFAULT = common.TERMSIGS_DEFAULT, default
    prev_full, common.TERMSIGS_FULL = common.TERMSIGS_FULL, full
    try:
        yield
    finally:
        common.TERMSIGS_DEFAULT, common.TERMSIGS_FULL = prev_def, prev_full


@skip.if_win32()
class test_reset_signals(Case):

    def test_shutdown_handler(self):
        with patch('sys.exit') as exit:
            _shutdown_cleanup(15, Mock())
            exit.assert_called()
            self.assertEqual(os.WTERMSIG(exit.call_args[0][0]), 15)

    def test_does_not_reset_ignored_signal(self, sigs=['SIGTERM']):
        with self.assert_context(sigs, [], signal.SIG_IGN) as (_, SET):
            SET.assert_not_called()

    def test_does_not_reset_if_current_is_None(self, sigs=['SIGTERM']):
        with self.assert_context(sigs, [], None) as (_, SET):
            SET.assert_not_called()

    def test_resets_for_SIG_DFL(self, sigs=['SIGTERM', 'SIGINT', 'SIGUSR1']):
        with self.assert_context(sigs, [], signal.SIG_DFL) as (_, SET):
            SET.assert_has_calls([
                call(signo(sig), _shutdown_cleanup) for sig in sigs
            ])

    def test_resets_for_obj(self, sigs=['SIGTERM', 'SIGINT', 'SIGUSR1']):
        with self.assert_context(sigs, [], object()) as (_, SET):
            SET.assert_has_calls([
                call(signo(sig), _shutdown_cleanup) for sig in sigs
            ])

    def test_handles_errors(self, sigs=['SIGTERM']):
        for exc in (OSError(), AttributeError(),
                    ValueError(), RuntimeError()):
            with self.assert_context(sigs, [], signal.SIG_DFL, exc) as (_, S):
                S.assert_called()

    @contextmanager
    def assert_context(self, default, full, get_returns=None, set_effect=None):
        with termsigs(default, full):
            with patch('signal.getsignal') as GET:
                with patch('signal.signal') as SET:
                    GET.return_value = get_returns
                    SET.side_effect = set_effect
                    reset_signals()
                    GET.assert_has_calls([
                        call(signo(sig)) for sig in default
                    ])
                    yield GET, SET


class test_restart_state(Case):

    def test_raises(self):
        s = restart_state(100, 1)  # max 100 restarts in 1 second.
        s.R = 99
        s.step()
        with self.assertRaises(s.RestartFreqExceeded):
            s.step()

    def test_time_passed_resets_counter(self):
        s = restart_state(100, 10)
        s.R, s.T = 100, time()
        with self.assertRaises(s.RestartFreqExceeded):
            s.step()
        s.R, s.T = 100, time()
        s.step(time() + 20)
        self.assertEqual(s.R, 1)


def timeouted_func(wait):
    sleep(wait)


def hold_exception_func(wait):
    try:
        sleep(wait)
    except SoftTimeLimitExceeded:
        sleep(wait)


class test_time_limits(Case):
    SOFT_TIMEOUT = 0.51
    TIMEOUT = 1.51

    def test_soft_timeout(self):
        p = Pool(1, soft_timeout=self.SOFT_TIMEOUT)
        start = time()
        self.assertRaises(SoftTimeLimitExceeded,
                          p.apply,
                          timeouted_func,
                          (self.SOFT_TIMEOUT + 1,))
        self.assertAlmostEqual(time()-start, round(self.SOFT_TIMEOUT), 1)

    def test_async_soft_timeout(self):
        p = Pool(1, soft_timeout=self.SOFT_TIMEOUT)
        start = time()
        res = p.apply_async(timeouted_func, (self.TIMEOUT + 1,))
        self.assertRaises(SoftTimeLimitExceeded, res.get)
        self.assertAlmostEqual(time()-start, round(self.SOFT_TIMEOUT), 1)

    def test_hard_timeout(self):
        p = Pool(1, soft_timeout=self.SOFT_TIMEOUT, timeout=self.TIMEOUT)
        start = time()
        self.assertRaises(TimeLimitExceeded,
                          p.apply,
                          hold_exception_func,
                          (self.TIMEOUT + 1,))
        self.assertAlmostEqual(time()-start, round(self.TIMEOUT), 1)

    def test_async_hard_timeout(self):
        p = Pool(1, soft_timeout=self.SOFT_TIMEOUT, timeout=self.TIMEOUT)
        start = time()
        res = p.apply_async(hold_exception_func, (self.TIMEOUT + 1,))
        self.assertRaises(TimeLimitExceeded, res.get)
        self.assertAlmostEqual(time()-start, round(self.TIMEOUT), 1)
