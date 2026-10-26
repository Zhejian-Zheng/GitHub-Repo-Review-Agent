def lookup(connection, username):
    query = "SELECT name FROM users WHERE name = '" + username + "'"
    return connection.execute(query).fetchall()
