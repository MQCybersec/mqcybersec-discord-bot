import discord
from discord.ext import commands
import logging
from util import fetch_ics, parse_ics, fetch_event_image, get_weekend_ctfs
from datetime import datetime, timedelta

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="weekendctfs",
        description="Show CTFs happening this weekend",
        guild=discord.Object(id=guild_id)
    )
    async def weekend_ctfs(interaction: discord.Interaction):
        required_permissions = ['view_channel', 'send_messages', 'embed_links']
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for weekendctfs command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'weekendctfs' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        try:
            await interaction.response.defer()
            
            ctfs = await get_weekend_ctfs(logger)
            
            if not ctfs:
                await interaction.followup.send("No CTFs found for this weekend!")
                return
                
            # Get next weekend's dates for the title
            today = datetime.now()
            saturday = today + timedelta(days=(5-today.weekday()) % 7)
            sunday = saturday + timedelta(days=1)
            weekend_str = f"{saturday.strftime('%B %d')} - {sunday.strftime('%B %d')}"
            
            embed = discord.Embed(
                title=f"CTFs This Weekend ({weekend_str})",
                color=discord.Color.blue(),
                description="Here are the upcoming CTFs for this weekend:"
            )
            
            # Display first 3 CTFs
            for i, ctf in enumerate(ctfs[:3], 1):
                embed.add_field(
                    name=f"{i}. {ctf['name']}",
                    value=f"Format: {ctf['format']}\n"
                        f"Teams Registered: {ctf['teams']}\n"
                        f"Weight: {ctf['weight']}\n"
                        f"[CTFtime Link]({ctf['url']})",
                    inline=False
                )
            
            # Add note about additional CTFs if there are more
            if len(ctfs) > 3:
                remaining = len(ctfs) - 3
                embed.add_field(
                    name="More CTFs",
                    value=f"*{remaining} more CTFs not listed. [View all on CTFtime](https://ctftime.org/event/list/upcoming)*",
                    inline=False
                )
                
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in weekend command: {str(e)}")
            await interaction.followup.send(f"Error fetching weekend CTFs: {str(e)}")