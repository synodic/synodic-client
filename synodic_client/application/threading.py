"""Reusable QThread worker runner.

Encapsulates the boilerplate for moving a ``QObject`` worker onto a
``QThread``, wiring lifecycle signals, and starting execution.

.. note::

   The caller **must** store the returned ``ThreadRunner`` as an instance
   attribute to prevent premature garbage collection.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class ThreadRunner(QObject):
    """Manages a worker ``QObject`` on a dedicated ``QThread``.

    Usage::

        runner = ThreadRunner(my_worker)
        runner.start()

    The runner connects ``thread.started`` → ``worker.run()`` and ensures
    both the thread and worker are cleaned up via ``deleteLater`` when the
    thread finishes.

    Callers should connect domain signals (``finished``, ``error``, etc.)
    on the *worker* before calling :meth:`start`.
    """

    #: Emitted when the managed thread finishes (for external cleanup).
    thread_finished = Signal()

    def __init__(self, worker: QObject, parent: QObject | None = None) -> None:
        """Initialise the runner.

        Args:
            worker: A ``QObject`` with a ``run()`` slot.  Must **not**
                already be parented — ``moveToThread`` requires this.
            parent: Optional parent for preventing GC.
        """
        super().__init__(parent)
        self._thread = QThread()
        self._worker = worker
        worker.moveToThread(self._thread)

        # Start the worker when the thread begins
        self._thread.started.connect(worker.run)  # type: ignore[attr-defined]

        # Quit-and-cleanup wiring: connect any ``finished`` / ``error``
        # signals on the worker so the thread stops automatically.
        for signal_name in ('finished', 'error'):
            signal = getattr(worker, signal_name, None)
            if signal is not None:
                signal.connect(self._thread.quit)

        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self.thread_finished)

    # -- public helpers --

    def start(self) -> None:
        """Start the background thread."""
        self._thread.start()

    def quit_and_wait(self) -> None:
        """Ask the thread to quit and block until it finishes."""
        self._thread.quit()
        self._thread.wait()

    @property
    def managed_thread(self) -> QThread:
        """Return the underlying ``QThread``."""
        return self._thread

    @property
    def worker(self) -> QObject:
        """Return the managed worker."""
        return self._worker
