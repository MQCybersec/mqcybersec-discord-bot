import discord
from discord.ext import commands
import logging
from util import fetch_ics, parse_ics, fetch_event_image

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctfinfo", 
        description="Get details about a CTF time event", 
        guild=discord.Object(id=guild_id)
    )
    async def ctftime(interaction: discord.Interaction, url: str):
        required_permissions = ['view_channel', 'send_messages', 'embed_links']
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for ctfinfo command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'ctfinfo' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        await interaction.response.defer()
        
        try:
            if not url.startswith('https://ctftime.org/event/'):
                await interaction.followup.send("Please provide a valid CTFtime event URL")
                return

            ics_data = await fetch_ics(url)
            event_info = parse_ics(ics_data)
            event_image = await fetch_event_image(url)

            embed = discord.Embed(
                title=event_info['name'],
                url=url,
                description=f"Running from <t:{event_info['start']}:F> to <t:{event_info['end']}:F>",
                color=discord.Color.blue()
            )
            
            if event_image:
                embed.set_thumbnail(url=event_image)
            
            if event_info['url']:
                embed.add_field(name="CTF URL", value=event_info['url'], inline=False)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"Error processing event: {str(e)}")