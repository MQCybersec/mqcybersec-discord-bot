import discord
from discord.ext import commands
import logging
from db import remove_reaction_role

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="publishctf",
        description="Publish a CTF channel and make it read-only",
        guild=discord.Object(id=guild_id)
    )
    async def publish_ctf(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        visible_role: discord.Role = None
    ):
        required_permissions = ['manage_roles', 'manage_channels', 'view_channel', 'send_messages']
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for publishctf command: {', '.join(missing_perms)}")
            await interaction.response.send_message(f"Bot is missing required permissions: {', '.join(missing_perms)}", ephemeral=True)
            return

        logger.info(f"Command 'publishctf' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        try:
            if not interaction.user.guild_permissions.manage_roles:
                await interaction.response.send_message("You don't have permission to manage roles!", ephemeral=True)
                return

            await interaction.response.defer()

            base_name = channel.name.replace('-', ' ').split(' ')[0]
            matching_roles = [r for r in interaction.guild.roles if r.name.lower().startswith(base_name.lower())]
            
            if not matching_roles:
                await interaction.followup.send(f"Could not find any roles starting with '{base_name}'!", ephemeral=True)
                return
                
            role = matching_roles[0]
            if len(matching_roles) > 1:
                channel_words = set(channel.name.replace('-', ' ').lower().split())
                best_match_score = 0
                
                for r in matching_roles:
                    role_words = set(r.name.lower().split())
                    match_score = len(channel_words.intersection(role_words))
                    if match_score > best_match_score:
                        best_match_score = match_score
                        role = r

            # Set up the overwrites based on whether a visible_role was specified
            new_overwrites = {
                interaction.guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    create_public_threads=True,
                    send_messages_in_threads=True
                )
            }
            
            # If a specific role is provided, make it visible only to that role
            # Otherwise, make it visible to everyone
            if visible_role:
                # Hide from @everyone but show to the specific role
                new_overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(
                    read_messages=False,
                    send_messages=False,
                    create_public_threads=False,
                    send_messages_in_threads=False
                )
                
                new_overwrites[visible_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    create_public_threads=False,
                    send_messages_in_threads=False
                )
                visibility_message = f"Channel {channel.mention} is now visible only to {visible_role.mention}"
            else:
                # Make visible to everyone
                new_overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    create_public_threads=False,
                    send_messages_in_threads=False
                )
                visibility_message = f"Channel {channel.mention} is now visible to everyone"

            await channel.edit(overwrites=new_overwrites)

            # Delete the associated role
            await role.delete()

            # Remove any reaction roles associated with the deleted role
            to_remove = []
            for message_id, role_info in bot.reaction_roles.items():
                if role_info['role_id'] == role.id:
                    to_remove.append(message_id)
                    remove_reaction_role(message_id)

            for message_id in to_remove:
                bot.reaction_roles.pop(message_id, None)

            await interaction.followup.send(
                f"CTF published!\n"
                f"- {visibility_message}\n"
                f"- Role '{role.name}' has been deleted\n"
                f"- Channel is now read-only",
                ephemeral=True
            )
            logger.info(f"CTF channel {channel.name} published by {interaction.user.name}#{interaction.user.discriminator}")
        except Exception as e:
            logger.error(f"Error in publishctf command: {str(e)}")
            await interaction.followup.send(f"Error publishing CTF: {str(e)}", ephemeral=True)