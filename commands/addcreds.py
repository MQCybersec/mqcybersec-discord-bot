import discord
from discord.ext import commands
import logging
import traceback
from typing import Optional, Literal

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_addcreds",
        description="Add credentials to an existing CTF channel",
        guild=discord.Object(id=guild_id)
    )
    async def add_creds(
        interaction: discord.Interaction,
        type: Literal['team', 'user', 'link'] = 'team',
        username: Optional[str] = None,
        password: Optional[str] = None,
        link: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        """
        Add credentials to a CTF channel
        
        Parameters:
        -----------
        type: The type of credentials ('team', 'user', or 'link')
        username: The username for team or user credentials
        password: The password for team or user credentials
        link: The direct login link/token for platforms like RCTF
        channel: The channel to add credentials to (defaults to current channel)
        """
        required_permissions = [
            'view_channel', 'send_messages', 'embed_links', 'read_message_history'
        ]
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for addcreds command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'addcreds' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        
        try:
            # Check if user has permission to manage channels
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message("You don't have permission to add credentials!", ephemeral=True)
                return
            
            # Validate parameters based on type
            if type in ('team', 'user') and (not username or not password):
                await interaction.response.send_message(f"Both username and password are required for {type} credentials!", ephemeral=True)
                return
            
            if type == 'link' and not link:
                await interaction.response.send_message("Link is required for link-type credentials!", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Determine which channel to use
            target_channel = channel if channel else interaction.channel
            
            # Check if the channel is a CTF channel
            if not target_channel.category or not target_channel.category.name.endswith("CTFs"):
                await interaction.followup.send("This command can only be used in a CTF channel!", ephemeral=True)
                return
            
            # Look for the welcome embed message in the channel
            welcome_message = None
            async for message in target_channel.history(limit=100):
                # Check if the message is from the bot and has an embed
                if message.author == bot.user and message.embeds and len(message.embeds) > 0:
                    embed = message.embeds[0]
                    # Look for CTF welcome embeds by checking if they have a title and URL
                    if embed.title and embed.url:
                        welcome_message = message
                        break
            
            if not welcome_message:
                # If no welcome message exists, we'll create a new one
                ctf_name = target_channel.name
                embed = discord.Embed(
                    title=f"{ctf_name} Information",
                    description="Information about this CTF.",
                    color=discord.Color.blue(),
                    url=link if type == 'link' else "https://ctftime.org/"
                )
                welcome_message = await target_channel.send(embed=embed)
            
            # Get the existing embed
            embed = welcome_message.embeds[0]
            
            # Create a copy of the embed
            new_embed = discord.Embed.from_dict(embed.to_dict())
            
            # Format credentials based on type
            if type == 'team':
                field_name = "Team Credentials"
                creds_value = f"**Username:** `{username}`\n**Password:** ||`{password}`||"
            elif type == 'user':
                field_name = "User Credentials"
                creds_value = f"**Username:** `{username}`\n**Password:** ||`{password}`||"
            else:  # link type
                field_name = "Login Link"
                creds_value = f"[Click to login]({link})"
                # Also update the embed URL if it's a welcome message
                if new_embed.title and "Information" in new_embed.title:
                    new_embed.url = link
            
            # Check if credentials field already exists
            field_found = False
            for i, field in enumerate(new_embed.fields):
                if field.name == field_name:
                    # Update existing field
                    new_embed.set_field_at(
                        i,
                        name=field_name,
                        value=creds_value,
                        inline=False
                    )
                    field_found = True
                    break
            
            # If no credentials field exists, add a new one
            if not field_found:
                new_embed.add_field(
                    name=field_name,
                    value=creds_value,
                    inline=False
                )
            
            # Update the message
            await welcome_message.edit(embed=new_embed)
            
            # Send confirmation
            ctf_name = new_embed.title or target_channel.name
            
            # Format confirmation message based on credential type
            if type == 'team':
                confirm_msg = f"Team credentials added to {ctf_name}!"
            elif type == 'user':
                confirm_msg = f"User credentials added to {ctf_name}!"
            else:  # link type
                confirm_msg = f"Login link added to {ctf_name}!"
                
            await interaction.followup.send(confirm_msg)
            logger.info(f"Added {type} credentials to CTF channel {target_channel.name} by {interaction.user.name}#{interaction.user.discriminator}")
            
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in addcreds command:\n{error_traceback}")
            await interaction.followup.send(f"Error adding credentials: {str(e)}", ephemeral=True)