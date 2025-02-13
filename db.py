import sqlite3
from os import path
def setup_database():
    if not path.exists("ctf_bot.db"):
        with open("ctf_bot.db", "w") as file:
            file.write("")
            file.close()

    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    # Create table
    c.execute('''CREATE TABLE IF NOT EXISTS reaction_roles
                (message_id INTEGER PRIMARY KEY,
                role_id INTEGER,
                emoji TEXT)''')
    
    conn.commit()
    conn.close()

def save_reaction_role(message_id, role_id, emoji):
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO reaction_roles VALUES (?, ?, ?)',
              (message_id, role_id, emoji))
    conn.commit()
    conn.close()

def load_reaction_roles():
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    c.execute('SELECT * FROM reaction_roles')
    roles = {row[0]: {'role_id': row[1], 'emoji': row[2]} for row in c.fetchall()}
    conn.close()
    return roles

def remove_reaction_role(message_id):
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    c.execute('DELETE FROM reaction_roles WHERE message_id = ?', (message_id,))
    conn.commit()
    conn.close()
