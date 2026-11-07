import random
from dataclasses import dataclass
from typing import Optional

# Fault names in the order in which they are checked; also the probability fields of ErrorSimulation
FAULTS = ("error_reply", "garbage", "no_reply", "slow_reply")

DEFAULT_SLOW_REPLY_S = 0.5


@dataclass(frozen=True)
class ErrorSimulation:
    """
    How often an emulator misbehaves on a valid command, so the framework can be watched handling failures
    with live emulators. Each probability is from 0 to 1, and together they are at most 1.

    :ivar error_reply: Probability of answering ``ERROR: simulated failure``.
    :ivar garbage: Probability of answering something that is not a number.
    :ivar no_reply: Probability of closing the connection without answering.
    :ivar slow_reply: Probability of answering correctly, but only after ``slow_reply_s``.
    :ivar slow_reply_s: Delay of a slow reply in seconds.
    :ivar seed: Seed of the random generator that picks the faults; with a seed the same requests fail on
        every run, which tests need. ``None`` picks different faults on every run.
    """
    error_reply: float = 0.0
    garbage: float = 0.0
    no_reply: float = 0.0
    slow_reply: float = 0.0
    slow_reply_s: float = DEFAULT_SLOW_REPLY_S
    seed: Optional[int] = None

    def new_generator(self) -> random.Random:
        """
        Creates the generator for picking faults. It is separate from the module-level ``random`` that the
        emulators use for their values, so a seed fixes the faults but not the measured values.

        :returns: A generator seeded with :attr:`seed`.
        """
        return random.Random(self.seed)

    def pick(self, generator: random.Random) -> Optional[str]:
        """
        Decides what happens to one request: one random number falls into one probability range in the order
        of :data:`FAULTS`, so the probabilities do not overlap.

        :param generator: Generator created by :meth:`new_generator`.
        :returns: The name of the fault from :data:`FAULTS`, or ``None`` for a normal reply.
        """
        roll = generator.random()
        threshold = 0.0
        for fault in FAULTS:
            threshold += getattr(self, fault)
            if roll < threshold:
                return fault
        return None
