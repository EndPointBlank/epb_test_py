import os
import psycopg2
import psycopg2.pool
import psycopg2.extras

_pool = None

def _get_pool():
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/epb_test_py_development")
        _pool = psycopg2.pool.ThreadedConnectionPool(4, 16, dsn)
    return _pool


class _Conn:
    def __enter__(self):
        self._conn = _get_pool().getconn()
        self._cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return self._cursor

    def __exit__(self, exc_type, *_):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._cursor.close()
        _get_pool().putconn(self._conn)


def setup():
    with _Conn() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schools (
                id       SERIAL PRIMARY KEY,
                name     TEXT NOT NULL,
                type     TEXT,
                location TEXT
            );
            CREATE TABLE IF NOT EXISTS classes (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                grade       TEXT,
                teacher_id  INTEGER,
                school_year TEXT
            );
            CREATE TABLE IF NOT EXISTS class_students (
                class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                student_id INTEGER NOT NULL,
                PRIMARY KEY (class_id, student_id)
            );
        """)

    with _Conn() as cur:
        cur.execute("SELECT COUNT(*) FROM schools")
        if cur.fetchone()["count"] == 0:
            cur.execute("""
                INSERT INTO schools (name, type, location) VALUES
                    ('Lincoln Elementary',    'Elementary', 'Springfield, IL'),
                    ('Westview Middle School','Middle',     'Shelbyville, IL'),
                    ('Riverside High School', 'High',       'Capital City, IL');
            """)

        cur.execute("SELECT COUNT(*) FROM classes")
        if cur.fetchone()["count"] == 0:
            cur.execute("""
                INSERT INTO classes (name, grade, teacher_id, school_year) VALUES
                    ('Math 101',    '3rd', 1, '2025-2026'),
                    ('English 201', '7th', 2, '2025-2026');
            """)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

def list_schools():
    with _Conn() as cur:
        cur.execute("SELECT * FROM schools ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


def add_school(name: str, type_: str, location: str) -> dict:
    with _Conn() as cur:
        cur.execute(
            "INSERT INTO schools (name, type, location) VALUES (%s, %s, %s) RETURNING *",
            (name, type_, location),
        )
        return dict(cur.fetchone())


def remove_school(school_id: int) -> bool:
    with _Conn() as cur:
        cur.execute("DELETE FROM schools WHERE id = %s", (school_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

def _class_with_students(cur, class_id: int):
    cur.execute("""
        SELECT c.*,
               COALESCE(array_agg(cs.student_id) FILTER (WHERE cs.student_id IS NOT NULL), '{}') AS student_ids
        FROM classes c
        LEFT JOIN class_students cs ON cs.class_id = c.id
        WHERE c.id = %s
        GROUP BY c.id
    """, (class_id,))
    row = cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["student_ids"] = list(d["student_ids"])
    return d


def list_classes():
    with _Conn() as cur:
        cur.execute("""
            SELECT c.*,
                   COALESCE(array_agg(cs.student_id) FILTER (WHERE cs.student_id IS NOT NULL), '{}') AS student_ids
            FROM classes c
            LEFT JOIN class_students cs ON cs.class_id = c.id
            GROUP BY c.id
            ORDER BY c.id
        """)
        result = []
        for row in cur.fetchall():
            d = dict(row)
            d["student_ids"] = list(d["student_ids"])
            result.append(d)
        return result


def add_class(name: str, grade: str, teacher_id: int, school_year: str) -> dict:
    with _Conn() as cur:
        cur.execute(
            "INSERT INTO classes (name, grade, teacher_id, school_year) VALUES (%s, %s, %s, %s) RETURNING id",
            (name, grade, teacher_id, school_year),
        )
        new_id = cur.fetchone()["id"]
        return _class_with_students(cur, new_id)


def remove_class(class_id: int) -> bool:
    with _Conn() as cur:
        cur.execute("DELETE FROM classes WHERE id = %s", (class_id,))
        return cur.rowcount > 0


def add_student_to_class(class_id: int, student_id: int):
    with _Conn() as cur:
        cur.execute("SELECT id FROM classes WHERE id = %s", (class_id,))
        if cur.fetchone() is None:
            return None, "Class not found"
        cur.execute("SELECT 1 FROM class_students WHERE class_id = %s AND student_id = %s", (class_id, student_id))
        if cur.fetchone():
            return None, "Student already in class"
        cur.execute("INSERT INTO class_students (class_id, student_id) VALUES (%s, %s)", (class_id, student_id))
        return _class_with_students(cur, class_id), None


def remove_student_from_class(class_id: int, student_id: int):
    with _Conn() as cur:
        cur.execute("SELECT id FROM classes WHERE id = %s", (class_id,))
        if cur.fetchone() is None:
            return None, "Class not found"
        cur.execute("DELETE FROM class_students WHERE class_id = %s AND student_id = %s", (class_id, student_id))
        if cur.rowcount == 0:
            return None, "Student not in class"
        return _class_with_students(cur, class_id), None
