import dbservice_client as dbs

from app.db.session import get_session


def db_session() -> dbs.Session:
    return get_session()
