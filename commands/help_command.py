import discord
import inspect
import importlib
import pkgutil
import sys
import logging

logger = logging.getLogger('discord_bot')

def get_command_descriptions(command_module):
    """
    Dynamically extract command descriptions from a module
    """
    descriptions = []
    
    # Check if the module has a 'setup' function
    if hasattr(command_module, 'setup'):
        setup_func = command_module.setup
        
        # Inspect the function to see if it can be called
        try:
            # Get the source code to extract command details
            source_lines = inspect.getsource(setup_func)
            
            # Try to find @bot.tree.command decorators
            import re
            command_matches = re.findall(
                r'@bot\.tree\.command\(\s*name="([^"]+)",\s*description="([^"]+)"', 
                source_lines
            )
            
            # If no matches, look for any @command or similar decorators
            if not command_matches:
                command_matches = re.findall(
                    r'@\w+\.command\(\s*name="?([^"\s]+)"?,\s*description="?([^"\n]+)"?', 
                    source_lines
                )
            
            # Add found commands to descriptions
            for name, desc in command_matches:
                descriptions.append({
                    'name': name,
                    'description': desc
                })
        except Exception as e:
            logger.warning(f"Could not extract command details from {command_module.__name__}: {e}")
    
    return descriptions

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="help",
        description="List all available bot commands",
        guild=discord.Object(id=guild_id)
    )
    async def help_command(interaction: discord.Interaction):
        """
        Dynamically generates a help command by extracting command information
        """
        # Create base embed
        help_embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here are all the available commands:",
            color=discord.Color.blue()
        )
        
        # Import the setup_commands function to get the module list
        from commands import setup_commands
        
        # Get the directory of the commands package
        import commands
        commands_dir = commands.__path__[0]
        
        # Collect all command descriptions
        all_commands = []
        
        # Dynamically import all modules in the commands package
        for _, modname, _ in pkgutil.iter_modules([commands_dir]):
            try:
                # Import the module
                full_modname = f'commands.{modname}'
                module = importlib.import_module(full_modname)
                
                # Get commands from this module
                module_commands = get_command_descriptions(module)
                all_commands.extend(module_commands)
            except Exception as e:
                logger.warning(f"Could not process module {modname}: {e}")
        
        # Group commands by category if possible
        categories = {}
        for cmd in all_commands:
            # Try to infer category from command name or description
            category = 'Other Commands'
            if 'ctf' in cmd['name'].lower():
                category = '🚩 CTF Commands'
            elif 'add' in cmd['name'].lower():
                category = '➕ Management Commands'
            elif 'setup' in cmd['name'].lower():
                category = '⚙️ Configuration Commands'
            
            if category not in categories:
                categories[category] = []
            categories[category].append(cmd)
        
        # Add fields for each category
        for category, cmds in categories.items():
            # Create command list for this category
            cmd_list = []
            for cmd in cmds:
                cmd_list.append(f"**`/{cmd['name']}`**: {cmd['description']}")
            
            help_embed.add_field(
                name=category,
                value="\n".join(cmd_list),
                inline=False
            )
        
        # Add footer
        help_embed.set_footer(
            text="Use these commands in the appropriate channel. Need more help? Contact server admins."
        )
        
        # Send the help embed
        await interaction.response.send_message(embed=help_embed, ephemeral=True)