def setup_commands(bot, guild_id, check_permissions):
    """
    Set up all command modules
    """
    from . import ctf_info
    from . import ctf_setup
    from . import publish_ctf
    from . import weekend_ctfs
    from . import ctf_solve
    from . import ctfd_challenges
    from . import challenge_tracker
    from . import ctf_addcreds
    from . import ctf_add_challenge
    from . import rctf_challenges
    from . import help_command
    from . import ctf_changeurl
    from . import ctf_changetime
    from . import ctf_converttoteams
    from . import ctf_converttosingle
    
    ctf_info.setup(bot, guild_id, check_permissions)
    ctf_setup.setup(bot, guild_id, check_permissions)
    publish_ctf.setup(bot, guild_id, check_permissions)
    weekend_ctfs.setup(bot, guild_id, check_permissions)
    ctf_solve.setup(bot, guild_id, check_permissions)
    ctfd_challenges.setup(bot, guild_id, check_permissions)
    challenge_tracker.setup(bot, guild_id, check_permissions)
    ctf_add_challenge.setup(bot, guild_id, check_permissions)
    ctf_addcreds.setup(bot, guild_id, check_permissions)
    rctf_challenges.setup(bot, guild_id, check_permissions)
    help_command.setup(bot,guild_id, check_permissions)
    ctf_changeurl.setup(bot, guild_id, check_permissions)
    ctf_changetime.setup(bot, guild_id, check_permissions)
    ctf_converttoteams.setup(bot, guild_id, check_permissions)
    ctf_converttosingle.setup(bot, guild_id, check_permissions)