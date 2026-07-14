"""Declared provider routing API."""


def provider_families():
    raise NotImplementedError


def select_provider(task, providers, budget_cents):
    raise NotImplementedError
