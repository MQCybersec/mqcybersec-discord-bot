def setup_commands(bot, guild_id, check_permissions):
    """
    Set up all command modules
    """
    from . import ctf_info
    from . import setup_ctf
    from . import publish_ctf
    from . import weekend_ctfs
    from . import solved
    from . import ctfd_challenges
    from . import challenge_tracker
    from . import addcreds
    
    ctf_info.setup(bot, guild_id, check_permissions)
    setup_ctf.setup(bot, guild_id, check_permissions)
    publish_ctf.setup(bot, guild_id, check_permissions)
    weekend_ctfs.setup(bot, guild_id, check_permissions)
    solved.setup(bot, guild_id, check_permissions)
    ctfd_challenges.setup(bot, guild_id, check_permissions)
    challenge_tracker.setup(bot, guild_id, check_permissions)
    addcreds.setup(bot, guild_id, check_permissions)