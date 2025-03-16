import discord
from discord.ext import commands
import logging
import traceback
from datetime import datetime

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="solved",
        description="Mark the current thread as solved with the flag",
        guild=discord.Object(id=guild_id)
    )
    async def solved(
        interaction: discord.Interaction,
        flag: str
    ):
        try:
            # Check if we're in a thread
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message("This command can only be used in a thread!", ephemeral=True)
                return

            thread = interaction.channel
            parent_channel = thread.parent
            
            # Check if the parent channel is in a category
            if not parent_channel.category:
                await interaction.response.send_message("This thread's channel is not in a category!", ephemeral=True)
                return
                
            # Check if the category is the current year's CTF category
            current_year = datetime.now().year
            if not parent_channel.category.name.endswith("CTFs"):
                await interaction.response.send_message(
                    f"This command can only be used in threads within a CTF category!", 
                    ephemeral=True
                )
                return

            # Log permissions for debugging
            thread_perms = thread.permissions_for(interaction.guild.me)
            parent_perms = parent_channel.permissions_for(interaction.guild.me)
            logger.info(f"Thread permissions: {thread_perms.value}")
            logger.info(f"Parent permissions: {parent_perms.value}")

            # Try to join the thread first
            try:
                await thread.join()
            except Exception as e:
                logger.error(f"Failed to join thread: {e}")

            # Check if we can manage threads
            if not thread_perms.manage_threads:
                await interaction.response.send_message(
                    "Bot does not have permission to manage threads!", 
                    ephemeral=True
                )
                return

            current_name = thread.name
            if current_name.startswith('[SOLVED] '):
                await interaction.response.send_message("This thread is already marked as solved!", ephemeral=True)
                return
                
            new_name = current_name.replace('[SOLVED]', '').strip()
            new_name = f'[SOLVED] {new_name}'
            
            # Parse the category and challenge name from the thread title
            try:
                # Try to extract [Category] from the thread name if it exists
                if current_name.startswith('[') and ']' in current_name:
                    category_end = current_name.find(']')
                    category_name = current_name[1:category_end].strip()
                    challenge_name = current_name[category_end+1:].strip()
                else:
                    # Otherwise just use the thread name directly
                    category_name = "Unknown"
                    challenge_name = current_name
            except:
                category_name = "Unknown"
                challenge_name = current_name

            try:
                # First, create and send the announcement in the parent channel
                solved_embed = discord.Embed(
                    title="🎉 Challenge Solved!",
                    description=f"**{challenge_name}** has been solved by {interaction.user.mention}!",
                    color=discord.Color.green()
                )
                
                solved_embed.add_field(name="Category", value=category_name, inline=True)
                solved_embed.add_field(name="Flag", value=f"```{flag}```", inline=False)
                solved_embed.add_field(name="Thread", value=f"[View Discussion]({thread.jump_url})", inline=False)
                
                # Add timestamp
                solved_embed.set_footer(text=f"Solved at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Send the announcement to the parent channel
                await parent_channel.send(embed=solved_embed)
                
                # Try to update the thread name
                await thread.edit(
                    name=new_name,
                    reason=f"Marked as solved by {interaction.user.name}"
                )
                
                # Send confirmation in the thread
                await interaction.response.send_message(
                    f"✅ Thread marked as solved!"
                )
                
                logger.info(f"Thread '{current_name}' marked as solved by {interaction.user.name}#{interaction.user.discriminator}")
            except discord.Forbidden:
                # If we get a Forbidden error, try to join the thread first and then retry
                try:
                    await thread.join()
                    await thread.edit(
                        name=new_name,
                        reason=f"Marked as solved by {interaction.user.name}"
                    )
                    
                    # Try to send the announcement again
                    await parent_channel.send(embed=solved_embed)
                    
                    await interaction.response.send_message(
                        f"✅ Thread marked as solved!"
                    )
                    
                    logger.info(f"Thread '{current_name}' marked as solved by {interaction.user.name}#{interaction.user.discriminator} (after joining)")
                except Exception as e:
                    raise Exception(f"Failed to edit thread even after joining: {str(e)}")
            
        except Exception as e:
            error_traceback = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
            logger.error(f"Error in solved command:\n{error_traceback}")
            await interaction.response.send_message(
                f"Error marking thread as solved. Please make sure the bot has the necessary permissions and is a member of the thread.",
                ephemeral=True
            )