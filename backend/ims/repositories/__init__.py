"""Repositories: the only code that talks to the database.

Route modules ask a repository for what they need ("get this PO", "count open cases for this slip") instead of
writing queries themselves, so every query for a table lives in one file (ims/repositories/mysql/<table>.py).
`ims/repositories/<name>.py` is the stable import name; it simply re-exports the MySQL implementation.
"""
