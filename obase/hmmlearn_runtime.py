"""obase.hmmlearn_runtime — Thin wrapper around hmmlearn for HMM fit/predict.

Install the optional extra to use this module::

    pip install obase[hmmlearn]

hmmlearn is imported lazily inside each method so the module can be imported
without the optional dependency installed.
"""
from __future__ import annotations

from typing import Any


class HmmlearnRuntime:
    """Static helpers for fitting and decoding Gaussian HMMs via hmmlearn."""

    @staticmethod
    def fit(
        observations: Any,
        *,
        n_states: int,
        max_iter: int = 100,
        covariance_type: str = "diag",
        random_state: int | None = 42,
    ) -> dict[str, Any]:
        """Fit a Gaussian HMM to *observations*.

        Args:
            observations: 1-D or 2-D array-like of shape (T,) or (T, D).
            n_states: Number of hidden states.
            max_iter: EM iteration cap.
            covariance_type: One of "diag", "full", "tied", "spherical".
            random_state: Seed for reproducibility.

        Returns:
            Dict with keys ``transmat``, ``means``, ``covars``,
            ``startprob``, ``n_states``, and ``_model`` (internal handle
            required by :meth:`predict`).

        Raises:
            ImportError: If hmmlearn is not installed.
        """
        try:
            from hmmlearn import hmm  # noqa: PLC0415
        except ImportError:
            raise ImportError(
                "hmmlearn is not installed. Run: pip install obase[hmmlearn]"
            ) from None

        import numpy as np  # noqa: PLC0415

        obs = np.array(observations, dtype=float)
        if obs.ndim == 1:
            obs = obs.reshape(-1, 1)

        model = hmm.GaussianHMM(
            n_components=n_states,
            n_iter=max_iter,
            covariance_type=covariance_type,
            random_state=random_state,
        )
        model.fit(obs)

        return {
            "n_states": n_states,
            "transmat": model.transmat_.tolist(),
            "means": model.means_.tolist(),
            "covars": model.covars_.tolist(),
            "startprob": model.startprob_.tolist(),
            "_model": model,
        }

    @staticmethod
    def predict(
        observations: Any,
        *,
        model: dict[str, Any],
    ) -> list[int]:
        """Decode the most likely hidden-state sequence (Viterbi).

        Args:
            observations: 1-D or 2-D array-like matching the training shape.
            model: Dict returned by :meth:`fit`.

        Returns:
            List of integer state indices, length == len(observations).

        Raises:
            ImportError: If hmmlearn is not installed.
            ValueError: If *model* does not contain the ``_model`` key.
        """
        try:
            from hmmlearn import hmm  # noqa: F401, PLC0415  # noqa: F401
        except ImportError:
            raise ImportError(
                "hmmlearn is not installed. Run: pip install obase[hmmlearn]"
            ) from None

        import numpy as np  # noqa: PLC0415

        _model = model.get("_model")
        if _model is None:
            raise ValueError(
                "model dict is missing '_model' key — pass the dict returned by fit()"
            )

        obs = np.array(observations, dtype=float)
        if obs.ndim == 1:
            obs = obs.reshape(-1, 1)

        states = _model.predict(obs)
        return [int(s) for s in states]
