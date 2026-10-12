# SPDX-License-Identifier: GPL-3.0-or-later
"""ZETA Core — the agent that controls the computer.

  request -> understand (locally, or via the model to pick the action)
          -> capability (a real action, with its own safety checks)
          -> execution -> verification against the real state -> reply

No reply says "done" unless verification has confirmed it.
"""
