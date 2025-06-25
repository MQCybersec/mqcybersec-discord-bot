import sqlite3
import json
import logging
from os import path

def setup_database():
    if not path.exists("ctf_bot.db"):
        with open("ctf_bot.db", "w") as file:
            file.write("")
        file.close()
    
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    # Create reaction_roles table with reaction_message_channel_id
    c.execute('''CREATE TABLE IF NOT EXISTS reaction_roles
                 (message_id INTEGER PRIMARY KEY,
                  role_id INTEGER,
                  emoji TEXT,
                  channel_id INTEGER,
                  reaction_message_channel_id INTEGER)''')
    
    # Create team_configs table for storing team configuration
    c.execute('''CREATE TABLE IF NOT EXISTS team_configs
                 (message_id INTEGER PRIMARY KEY,
                  ctf_name TEXT,
                  team_size INTEGER,
                  category_id INTEGER,
                  guild_id INTEGER,
                  add_texit_bot BOOLEAN)''')
    
    # Create team_members table for tracking team membership
    c.execute('''CREATE TABLE IF NOT EXISTS team_members
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  message_id INTEGER,
                  team_number INTEGER,
                  user_id INTEGER,
                  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(message_id, user_id))''')
    
    conn.commit()
    conn.close()

def save_reaction_role(message_id, role_id, emoji, channel_id=None, reaction_message_channel_id=None):
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        # Check if columns exist and add them if missing
        c.execute("PRAGMA table_info(reaction_roles)")
        columns = [column[1] for column in c.fetchall()]
        
        if 'channel_id' not in columns:
            logger = logging.getLogger('discord_bot')
            logger.info("Adding channel_id column to reaction_roles table")
            c.execute('ALTER TABLE reaction_roles ADD COLUMN channel_id INTEGER')
            conn.commit()
        
        if 'reaction_message_channel_id' not in columns:
            logger = logging.getLogger('discord_bot')
            logger.info("Adding reaction_message_channel_id column to reaction_roles table")
            c.execute('ALTER TABLE reaction_roles ADD COLUMN reaction_message_channel_id INTEGER')
            conn.commit()
        
        # Insert or update the reaction role with both channel IDs
        c.execute('''INSERT OR REPLACE INTO reaction_roles 
                     (message_id, role_id, emoji, channel_id, reaction_message_channel_id) 
                     VALUES (?, ?, ?, ?, ?)''',
                  (message_id, role_id, emoji, channel_id, reaction_message_channel_id))
        conn.commit()
        
        logger = logging.getLogger('discord_bot')
        logger.info(f"Saved reaction role: message_id={message_id}, role_id={role_id}, emoji={emoji}, channel_id={channel_id}, reaction_message_channel_id={reaction_message_channel_id}")
        
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error saving reaction role: {str(e)}")
        raise
    finally:
        conn.close()

def get_ctf_by_channel(channel_id):
    """Get CTF reaction message ID by channel ID"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT message_id FROM reaction_roles WHERE channel_id = ?', (channel_id,))
        row = c.fetchone()
        
        if row:
            logger = logging.getLogger('discord_bot')
            logger.info(f"Found CTF message {row[0]} for channel {channel_id}")
            return row[0]
        else:
            logger = logging.getLogger('discord_bot')
            logger.warning(f"No CTF found for channel {channel_id}")
            return None
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error getting CTF by channel {channel_id}: {str(e)}")
        raise
    finally:
        conn.close()

def get_reaction_message_channel(message_id):
    """Get the channel ID where the reaction message was posted"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT reaction_message_channel_id FROM reaction_roles WHERE message_id = ?', (message_id,))
        row = c.fetchone()
        
        if row and row[0]:
            logger = logging.getLogger('discord_bot')
            logger.info(f"Found reaction message channel {row[0]} for message {message_id}")
            return row[0]
        else:
            logger = logging.getLogger('discord_bot')
            logger.warning(f"No reaction message channel found for message {message_id}")
            return None
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error getting reaction message channel for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def load_reaction_roles():
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    # Check if columns exist and add them if missing
    c.execute("PRAGMA table_info(reaction_roles)")
    columns = [column[1] for column in c.fetchall()]
    
    if 'channel_id' not in columns:
        c.execute('ALTER TABLE reaction_roles ADD COLUMN channel_id INTEGER')
        conn.commit()
    
    if 'reaction_message_channel_id' not in columns:
        c.execute('ALTER TABLE reaction_roles ADD COLUMN reaction_message_channel_id INTEGER')
        conn.commit()
    
    # Load basic reaction roles with all columns
    c.execute('SELECT * FROM reaction_roles')
    roles = {}
    for row in c.fetchall():
        message_id = row[0]
        roles[message_id] = {
            'role_id': row[1], 
            'emoji': row[2],
            'channel_id': row[3] if len(row) > 3 else None,
            'reaction_message_channel_id': row[4] if len(row) > 4 else None
        }
    
    # Load team configurations and merge them
    c.execute('SELECT * FROM team_configs')
    for row in c.fetchall():
        message_id = row[0]
        if message_id in roles:
            # Merge team config into the existing reaction role data
            roles[message_id]['team_config'] = {
                'ctf_name': row[1],
                'team_size': row[2],
                'category_id': row[3],
                'guild_id': row[4],
                'add_texit_bot': bool(row[5])
            }
            # Add event_role_id if it exists
            if roles[message_id]['role_id']:
                roles[message_id]['team_config']['event_role_id'] = roles[message_id]['role_id']
            
            logger = logging.getLogger('discord_bot')
            logger.info(f"Loaded team config for message {message_id}: {roles[message_id]['team_config']['ctf_name']}")
    
    conn.close()
    
    logger = logging.getLogger('discord_bot')
    logger.info(f"Loaded {len(roles)} reaction roles with {len([r for r in roles.values() if 'team_config' in r])} team-based CTFs")
    
    return roles

def remove_reaction_role(message_id):
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    c.execute('DELETE FROM reaction_roles WHERE message_id = ?', (message_id,))
    conn.commit()
    conn.close()

# Team-related functions

def save_team_info(message_id, team_config):
    """Save team configuration for a CTF message"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        c.execute('''INSERT OR REPLACE INTO team_configs 
                     (message_id, ctf_name, team_size, category_id, guild_id, add_texit_bot) 
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (message_id, team_config['ctf_name'], team_config['team_size'],
                   team_config['category_id'], team_config['guild_id'],
                   team_config.get('add_texit_bot', False)))
        
        conn.commit()
        logger = logging.getLogger('discord_bot')
        logger.info(f"Successfully saved team config for message {message_id}: {team_config['ctf_name']}")
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error saving team config for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def get_team_info(message_id):
    """Get team configuration for a CTF message"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT * FROM team_configs WHERE message_id = ?', (message_id,))
        row = c.fetchone()
        
        if row:
            config = {
                'ctf_name': row[1],
                'team_size': row[2],
                'category_id': row[3],
                'guild_id': row[4],
                'add_texit_bot': bool(row[5])
            }
            logger = logging.getLogger('discord_bot')
            logger.debug(f"Retrieved team config for message {message_id}: {config['ctf_name']}")
            return config
        else:
            logger = logging.getLogger('discord_bot')
            logger.warning(f"No team config found for message {message_id}")
            return None
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error retrieving team config for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def add_team_member(message_id, team_number, user_id):
    """Add a user to a specific team"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        c.execute('''INSERT INTO team_members (message_id, team_number, user_id) 
                     VALUES (?, ?, ?)''',
                  (message_id, team_number, user_id))
        conn.commit()
        logger = logging.getLogger('discord_bot')
        logger.info(f"Added user {user_id} to team {team_number} for message {message_id}")
        return True
    except sqlite3.IntegrityError as e:
        # User already in a team for this CTF
        logger = logging.getLogger('discord_bot')
        logger.warning(f"User {user_id} already in a team for message {message_id}: {str(e)}")
        return False
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error adding user {user_id} to team {team_number} for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def remove_team_member(message_id, user_id):
    """Remove a user from their team"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        # Get team info before deletion for logging
        c.execute('SELECT team_number FROM team_members WHERE message_id = ? AND user_id = ?',
                  (message_id, user_id))
        row = c.fetchone()
        team_number = row[0] if row else None
        
        c.execute('DELETE FROM team_members WHERE message_id = ? AND user_id = ?',
                  (message_id, user_id))
        
        deleted_count = c.rowcount
        conn.commit()
        
        logger = logging.getLogger('discord_bot')
        if deleted_count > 0:
            logger.info(f"Removed user {user_id} from team {team_number} for message {message_id}")
        else:
            logger.warning(f"User {user_id} was not found in any team for message {message_id}")
            
        return team_number  # Return the team number for cleanup logic
            
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error removing user {user_id} from team for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def remove_empty_team(message_id, team_number):
    """Remove all records for an empty team"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        # Double-check the team is actually empty
        c.execute('SELECT COUNT(*) FROM team_members WHERE message_id = ? AND team_number = ?',
                  (message_id, team_number))
        member_count = c.fetchone()[0]
        
        if member_count == 0:
            # Remove any remaining team member records (should be none, but just in case)
            c.execute('DELETE FROM team_members WHERE message_id = ? AND team_number = ?',
                      (message_id, team_number))
            
            conn.commit()
            
            logger = logging.getLogger('discord_bot')
            logger.info(f"Cleaned up database records for empty team {team_number} in message {message_id}")
            return True
        else:
            logger = logging.getLogger('discord_bot')
            logger.warning(f"Attempted to remove team {team_number} but it has {member_count} members")
            return False
            
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error removing empty team {team_number} for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def get_available_team_slot(message_id, team_size):
    """Find the lowest numbered team with available slots, or return next team number"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        # Get team member counts
        c.execute('''SELECT team_number, COUNT(*) as member_count 
                     FROM team_members 
                     WHERE message_id = ? 
                     GROUP BY team_number 
                     ORDER BY team_number''',
                  (message_id,))
        teams = c.fetchall()
        
        logger = logging.getLogger('discord_bot')
        logger.debug(f"Current teams for message {message_id}: {teams}")
        
        # Check for available slots in existing teams
        for team_num, member_count in teams:
            if member_count < team_size:
                logger.info(f"Found available slot in team {team_num} ({member_count}/{team_size})")
                return team_num
        
        # Find next available team number
        if teams:
            # Find the lowest unused team number
            existing_team_numbers = [team[0] for team in teams]
            next_team = 1
            while next_team in existing_team_numbers:
                next_team += 1
        else:
            next_team = 1
            
        logger.info(f"No available slots found, creating new team {next_team}")
        return next_team
        
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error finding available team slot for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def get_team_members(message_id, user_id=None, team_number=None):
    """Get team members - either for a specific user or team number"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        if user_id:
            # Get the team info for a specific user
            c.execute('''SELECT team_number FROM team_members 
                         WHERE message_id = ? AND user_id = ?''',
                      (message_id, user_id))
            row = c.fetchone()
            
            if row:
                logger = logging.getLogger('discord_bot')
                logger.debug(f"User {user_id} is in team {row[0]} for message {message_id}")
                return {'team_number': row[0]}
            return None
        
        elif team_number:
            # Get all users in a specific team
            c.execute('''SELECT user_id FROM team_members 
                         WHERE message_id = ? AND team_number = ?
                         ORDER BY joined_at''',
                      (message_id, team_number))
            rows = c.fetchall()
            
            members = [row[0] for row in rows]
            logger = logging.getLogger('discord_bot')
            logger.debug(f"Team {team_number} for message {message_id} has {len(members)} members")
            return members
        
        else:
            # Get all team members for a CTF
            c.execute('''SELECT team_number, user_id FROM team_members 
                         WHERE message_id = ?
                         ORDER BY team_number, joined_at''',
                      (message_id,))
            rows = c.fetchall()
            
            teams = {}
            for team_num, user_id in rows:
                if team_num not in teams:
                    teams[team_num] = []
                teams[team_num].append(user_id)
            
            logger = logging.getLogger('discord_bot')
            logger.debug(f"Message {message_id} has {len(teams)} teams with total {len(rows)} members")
            return teams
            
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error getting team members for message {message_id}: {str(e)}")
        raise
    finally:
        conn.close()

def get_user_team_number(message_id, user_id):
    """Get the team number for a specific user"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    c.execute('''SELECT team_number FROM team_members 
                 WHERE message_id = ? AND user_id = ?''',
              (message_id, user_id))
    row = c.fetchone()
    conn.close()
    
    return row[0] if row else None

def get_team_count(message_id, team_number):
    """Get the number of members in a specific team"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    c.execute('''SELECT COUNT(*) FROM team_members 
                 WHERE message_id = ? AND team_number = ?''',
              (message_id, team_number))
    count = c.fetchone()[0]
    conn.close()
    
    return count

def cleanup_ctf_data(message_id):
    """Remove all data associated with a CTF (useful for cleanup)"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    # Remove from all tables
    c.execute('DELETE FROM reaction_roles WHERE message_id = ?', (message_id,))
    c.execute('DELETE FROM team_configs WHERE message_id = ?', (message_id,))
    c.execute('DELETE FROM team_members WHERE message_id = ?', (message_id,))
    
    conn.commit()
    conn.close()

def load_team_configs():
    """Load all team configurations (useful for bot startup)"""
    conn = sqlite3.connect('ctf_bot.db')
    c = conn.cursor()
    
    try:
        c.execute('SELECT * FROM team_configs')
        configs = {}
        
        for row in c.fetchall():
            message_id = row[0]
            configs[message_id] = {
                'ctf_name': row[1],
                'team_size': row[2],
                'category_id': row[3],
                'guild_id': row[4],
                'add_texit_bot': bool(row[5])
            }
        
        logger = logging.getLogger('discord_bot')
        logger.info(f"Loaded {len(configs)} team configurations from database")
        return configs
        
    except Exception as e:
        logger = logging.getLogger('discord_bot')
        logger.error(f"Error loading team configurations: {str(e)}")
        raise
    finally:
        conn.close()