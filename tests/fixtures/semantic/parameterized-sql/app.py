def lookup(connection, username):
    return connection.execute("SELECT name FROM users WHERE name = ?", (username,)).fetchall()
