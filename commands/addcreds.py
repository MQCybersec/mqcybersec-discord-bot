import discord
from discord.ext import commands
import logging
import traceback

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_addcreds",
        description="Add team credentials to an existing CTF channel",
        guild=discord.Object(id=guild_id)
    )
    async def add_creds(
        interaction: discord.Interaction,
        username: str,
        password: str,
        channel: discord.TextChannel = None
    ):
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
                await interaction.response.send_message("You don't have permission to add team credentials!", ephemeral=True)
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
                await interaction.followup.send("Could not find the CTF information message in this channel. Please make sure you're using a properly set up CTF channel.", ephemeral=True)
                return
            
            # Get the existing embed
            embed = welcome_message.embeds[0]
            
            # Create a copy of the embed and add credentials field
            new_embed = discord.Embed.from_dict(embed.to_dict())
            
            # Format credentials with spoilered password
            creds_value = f"**Username:** `{username}`\n**Password:** ||`{password}`||"
            
            # Check if credentials field already exists
            field_found = False
            for i, field in enumerate(new_embed.fields):
                if field.name == "Team Credentials":
                    # Update existing field
                    new_embed.set_field_at(
                        i,
                        name="Team Credentials",
                        value=creds_value,
                        inline=False
                    )
                    field_found = True
                    break
            
            # If no credentials field exists, add a new one
            if not field_found:
                new_embed.add_field(
                    name="Team Credentials",
                    value=creds_value,
                    inline=False
                )
            
            # Update the message
            await welcome_message.edit(embed=new_embed)
            
            # Send confirmation
            ctf_name = new_embed.title or target_channel.name
            await interaction.followup.send(f"Team credentials added to {ctf_name}!", ephemeral=True)
            logger.info(f"Added credentials to CTF channel {target_channel.name} by {interaction.user.name}#{interaction.user.discriminator}")
            
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in addcreds command:\n{error_traceback}")
            await interaction.followup.send(f"Error adding credentials: {str(e)}", ephemeral=True)