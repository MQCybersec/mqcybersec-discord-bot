import discord
from discord.ext import commands
import logging
import asyncio
import traceback
from datetime import datetime
import json
import os

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

# Simple storage for assignments
class AssignmentStore:
    def __init__(self):
        self.data = {
            "assignments": {},  # {channel_id: {thread_id: [user_id, user_id]}}
            "summaries": {}     # {channel_id: message_id}
        }
        self.file_path = "assignments.json"
        self.load()
    
    def load(self):
        """Load data from file"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r") as f:
                    loaded_data = json.load(f)
                    # Convert string keys to integers
                    assignments = {}
                    for channel_id, threads in loaded_data.get("assignments", {}).items():
                        assignments[int(channel_id)] = {}
                        for thread_id, users in threads.items():
                            assignments[int(channel_id)][int(thread_id)] = [int(user) for user in users]
                    
                    summaries = {}
                    for channel_id, message_id in loaded_data.get("summaries", {}).items():
                        summaries[int(channel_id)] = int(message_id)
                    
                    self.data = {
                        "assignments": assignments,
                        "summaries": summaries
                    }
                    logger.info(f"Loaded assignment data from {self.file_path}")
        except Exception as e:
            logger.error(f"Error loading assignment data: {e}")
    
    def save(self):
        """Save data to file"""
        try:
            # Convert data for JSON serialization (int keys to strings)
            serializable = {
                "assignments": {},
                "summaries": {}
            }
            
            for channel_id, threads in self.data["assignments"].items():
                serializable["assignments"][str(channel_id)] = {}
                for thread_id, users in threads.items():
                    serializable["assignments"][str(channel_id)][str(thread_id)] = [str(user) for user in users]
            
            for channel_id, message_id in self.data["summaries"].items():
                serializable["summaries"][str(channel_id)] = str(message_id)
            
            with open(self.file_path, "w") as f:
                json.dump(serializable, f)
        except Exception as e:
            logger.error(f"Error saving assignment data: {e}")
    
    def assign_user(self, channel_id, thread_id, user_id):
        """Assign a user to a thread"""
        # Initialize if needed
        if str(channel_id) not in self.data["assignments"]:
            self.data["assignments"][channel_id] = {}
        
        # Remove user from any existing assignments in this channel
        for thread, users in list(self.data["assignments"][channel_id].items()):
            if user_id in users:
                users.remove(user_id)
                # Clean up empty entries
                if not users:
                    del self.data["assignments"][channel_id][thread]
        
        # Create thread entry if needed
        if thread_id not in self.data["assignments"][channel_id]:
            self.data["assignments"][channel_id][thread_id] = []
        
        # Add user to thread
        if user_id not in self.data["assignments"][channel_id][thread_id]:
            self.data["assignments"][channel_id][thread_id].append(user_id)
            self.save()
            return True
        return False
    
    def remove_user(self, channel_id, thread_id, user_id):
        """Remove a user from a thread"""
        if (channel_id in self.data["assignments"] and
            thread_id in self.data["assignments"][channel_id] and
            user_id in self.data["assignments"][channel_id][thread_id]):
            
            self.data["assignments"][channel_id][thread_id].remove(user_id)
            
            # Clean up empty entries
            if not self.data["assignments"][channel_id][thread_id]:
                del self.data["assignments"][channel_id][thread_id]
            
            if not self.data["assignments"][channel_id]:
                del self.data["assignments"][channel_id]
            
            self.save()
            return True
        return False
    
    def get_users_for_thread(self, channel_id, thread_id):
        """Get users assigned to a thread"""
        return self.data["assignments"].get(channel_id, {}).get(thread_id, [])
    
    def get_all_assignments(self, channel_id):
        """Get all assignments for a channel"""
        return self.data["assignments"].get(channel_id, {})
    
    def set_summary_message(self, channel_id, message_id):
        """Set the summary message ID for a channel"""
        self.data["summaries"][channel_id] = message_id
        self.save()
    
    def get_summary_message(self, channel_id):
        """Get the summary message ID for a channel"""
        return self.data["summaries"].get(channel_id)
    
    def clear_solved_threads(self):
        """Remove solved threads from assignments"""
        # This is handled during updates rather than proactively

# Create a work button
class WorkButton(discord.ui.Button):
    def __init__(self, thread_id):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Work on this",
            custom_id=f"work_{thread_id}"
        )
    
    async def callback(self, interaction):
        # We'll handle this in the main setup function
        pass

# Create a stop button
class StopButton(discord.ui.Button):
    def __init__(self, thread_id):
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Stop working on this",
            custom_id=f"stop_{thread_id}"
        )
    
    async def callback(self, interaction):
        # We'll handle this in the main setup function
        pass

# Challenge tracker view
class ChallengeView(discord.ui.View):
    def __init__(self, thread_id):
        super().__init__(timeout=None)
        self.add_item(WorkButton(thread_id))
        self.add_item(StopButton(thread_id))

def setup(bot, guild_id, check_permissions):
    """Set up the challenge tracker system"""
    # Create assignment store if it doesn't exist
    if not hasattr(bot, "assignments"):
        bot.assignments = AssignmentStore()
    
    # Create a persistent view for the buttons
    @bot.event
    async def on_ready():
        # Register the persistent view
        bot.add_view(ChallengeView(0))  # A generic view that we'll identify by custom_id
    
    # Handle thread creation
    @bot.event
    async def on_thread_create(thread):
        try:
            # Only process threads in CTF categories
            if (thread.parent and 
                thread.parent.category and 
                thread.parent.category.name.endswith("CTFs")):
                
                # Don't add tracker to solved threads
                if "[SOLVED]" in thread.name:
                    return
                
                # Create embed with buttons
                embed = discord.Embed(
                    title="📝 Challenge Assignment Tracker",
                    description="Use the buttons below to indicate if you're working on this challenge.",
                    color=discord.Color.blue()
                )
                
                embed.add_field(
                    name="Currently Working On This:",
                    value="Nobody is working on this challenge yet.",
                    inline=False
                )
                
                # Each thread gets its own view
                view = ChallengeView(thread.id)
                
                # Send the message
                await thread.send(embed=embed, view=view)
                
                # Update the summary in the parent channel
                await update_summary(thread.parent, bot)
                
                logger.info(f"Added challenge tracker to new thread: {thread.name}")
        except Exception as e:
            logger.error(f"Error adding challenge tracker to thread: {str(e)}")
    
    # Handle thread updates (for solved challenges)
    @bot.event
    async def on_thread_update(before, after):
        try:
            # Check if thread was marked as solved
            if (not before.name.startswith("[SOLVED]") and 
                after.name.startswith("[SOLVED]") and
                after.parent):
                
                # Get the parent channel
                channel_id = after.parent.id
                thread_id = after.id
                
                # Clear this thread from assignments
                assignments = bot.assignments.get_all_assignments(channel_id)
                if thread_id in assignments:
                    for user_id in assignments[thread_id]:
                        bot.assignments.remove_user(channel_id, thread_id, user_id)
                
                # Update the summary
                await update_summary(after.parent, bot)
                
                logger.info(f"Removed solved thread from assignments: {after.name}")
        except Exception as e:
            logger.error(f"Error handling thread update: {str(e)}")
    
    # Command to refresh the summary
    @bot.tree.command(
        name="refreshchallenges",
        description="Refresh the challenge assignments summary",
        guild=discord.Object(id=guild_id)
    )
    async def refresh_challenges(interaction: discord.Interaction):
        try:
            channel = interaction.channel
            
            # Check if this is a CTF channel
            if not channel.category or not channel.category.name.endswith("CTFs"):
                await interaction.response.send_message(
                    "This command can only be used in channels within a CTF category!",
                    ephemeral=True
                )
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Update the summary
            await update_summary(channel, bot)
            
            # Count threads that need embeds
            count = 0
            for thread in channel.threads:
                # Skip solved threads
                if "[SOLVED]" in thread.name:
                    continue
                
                # Check if thread has tracker embed
                has_tracker = False
                async for message in thread.history(limit=20):
                    if (message.author == bot.user and 
                        message.embeds and 
                        len(message.embeds) > 0 and 
                        message.embeds[0].title == "📝 Challenge Assignment Tracker"):
                        has_tracker = True
                        break
                
                # Add tracker if missing
                if not has_tracker:
                    embed = discord.Embed(
                        title="📝 Challenge Assignment Tracker",
                        description="Use the buttons below to indicate if you're working on this challenge.",
                        color=discord.Color.blue()
                    )
                    
                    users = bot.assignments.get_users_for_thread(channel.id, thread.id)
                    if users:
                        user_mentions = []
                        for user_id in users:
                            user = bot.get_user(user_id)
                            if user:
                                user_mentions.append(user.mention)
                        
                        if user_mentions:
                            embed.add_field(
                                name="Currently Working On This:",
                                value="\n".join(user_mentions),
                                inline=False
                            )
                        else:
                            embed.add_field(
                                name="Currently Working On This:",
                                value="Nobody is working on this challenge yet.",
                                inline=False
                            )
                    else:
                        embed.add_field(
                            name="Currently Working On This:",
                            value="Nobody is working on this challenge yet.",
                            inline=False
                        )
                    
                    view = ChallengeView(thread.id)
                    await thread.send(embed=embed, view=view)
                    count += 1
            
            await interaction.followup.send(
                f"Challenge assignments refreshed! Added tracking embeds to {count} threads that were missing them.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in refresh_challenges command: {str(e)}")
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)
    
    # Handle button interactions
    @bot.listen("on_interaction")
    async def handle_buttons(interaction):
        try:
            # Skip if not a button interaction
            if not isinstance(interaction, discord.Interaction) or not interaction.data or interaction.data.get("component_type") != 2:
                return
            
            # Get the custom ID
            custom_id = interaction.data.get("custom_id", "")
            
            # Skip if not our buttons
            if not custom_id.startswith(("work_", "stop_")):
                return
            
            # We're in a thread, so get the thread and parent
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message("This button only works in challenge threads.", ephemeral=True)
                return
            
            thread = interaction.channel
            if not thread.parent:
                await interaction.response.send_message("Could not find parent channel.", ephemeral=True)
                return
            
            # Process the button press
            if custom_id.startswith("work_"):
                # User wants to work on this challenge
                await interaction.response.defer(ephemeral=True)
                
                # Get user and thread IDs
                user_id = interaction.user.id
                thread_id = thread.id
                channel_id = thread.parent.id
                
                # Assign user to thread
                assigned = bot.assignments.assign_user(channel_id, thread_id, user_id)
                
                # Update the thread embed
                await update_thread_embed(thread, bot)
                
                # Update the summary embed
                await update_summary(thread.parent, bot)
                
                # Confirm to user
                if assigned:
                    await interaction.followup.send("You are now working on this challenge!", ephemeral=True)
                else:
                    await interaction.followup.send("You're already working on this challenge.", ephemeral=True)
            
            elif custom_id.startswith("stop_"):
                # User wants to stop working on this challenge
                await interaction.response.defer(ephemeral=True)
                
                # Get user and thread IDs
                user_id = interaction.user.id
                thread_id = thread.id
                channel_id = thread.parent.id
                
                # Remove user from thread
                removed = bot.assignments.remove_user(channel_id, thread_id, user_id)
                
                # Update the thread embed
                await update_thread_embed(thread, bot)
                
                # Update the summary embed
                await update_summary(thread.parent, bot)
                
                # Confirm to user
                if removed:
                    await interaction.followup.send("You are no longer working on this challenge.", ephemeral=True)
                else:
                    await interaction.followup.send("You weren't assigned to this challenge.", ephemeral=True)
        
        except Exception as e:
            logger.error(f"Error handling button interaction: {str(e)}")
            try:
                await interaction.followup.send("An error occurred. Please try again.", ephemeral=True)
            except:
                pass

async def update_thread_embed(thread, bot):
    """Update the challenge tracker embed in a thread"""
    try:
        # Find the tracker embed
        async for message in thread.history(limit=20):
            if (message.author == bot.user and 
                message.embeds and 
                len(message.embeds) > 0 and 
                message.embeds[0].title == "📝 Challenge Assignment Tracker"):
                
                # Get assigned users
                users = bot.assignments.get_users_for_thread(thread.parent.id, thread.id)
                
                # Create updated embed
                embed = discord.Embed(
                    title="📝 Challenge Assignment Tracker",
                    description="Use the buttons below to indicate if you're working on this challenge.",
                    color=discord.Color.blue()
                )
                
                if users:
                    user_mentions = []
                    for user_id in users:
                        user = bot.get_user(user_id)
                        if user:
                            user_mentions.append(user.mention)
                    
                    if user_mentions:
                        embed.add_field(
                            name="Currently Working On This:",
                            value="\n".join(user_mentions),
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name="Currently Working On This:",
                            value="Nobody is working on this challenge yet.",
                            inline=False
                        )
                else:
                    embed.add_field(
                        name="Currently Working On This:",
                        value="Nobody is working on this challenge yet.",
                        inline=False
                    )
                
                # Update the message
                await message.edit(embed=embed)
                return
        
        # If we didn't find the embed, create a new one
        embed = discord.Embed(
            title="📝 Challenge Assignment Tracker",
            description="Use the buttons below to indicate if you're working on this challenge.",
            color=discord.Color.blue()
        )
        
        users = bot.assignments.get_users_for_thread(thread.parent.id, thread.id)
        
        if users:
            user_mentions = []
            for user_id in users:
                user = bot.get_user(user_id)
                if user:
                    user_mentions.append(user.mention)
            
            if user_mentions:
                embed.add_field(
                    name="Currently Working On This:",
                    value="\n".join(user_mentions),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Currently Working On This:",
                    value="Nobody is working on this challenge yet.",
                    inline=False
                )
        else:
            embed.add_field(
                name="Currently Working On This:",
                value="Nobody is working on this challenge yet.",
                inline=False
            )
        
        view = ChallengeView(thread.id)
        await thread.send(embed=embed, view=view)
    
    except Exception as e:
        logger.error(f"Error updating thread embed: {str(e)}")

async def update_summary(channel, bot):
    """Update or create the summary embed in a channel"""
    try:
        # Check if we have a summary message ID
        summary_id = bot.assignments.get_summary_message(channel.id)
        summary_message = None
        
        if summary_id:
            try:
                summary_message = await channel.fetch_message(summary_id)
            except:
                # Message not found, we'll create a new one
                pass
        
        # Get all assignments for this channel
        assignments = bot.assignments.get_all_assignments(channel.id)
        
        # Create the embed
        embed = discord.Embed(
            title="👥 Current Challenge Assignments",
            color=discord.Color.purple()
        )
        
        if not assignments:
            embed.description = "No challenges are currently being worked on."
        else:
            embed.description = "Here's who's working on what:"
            
            for thread_id, user_ids in assignments.items():
                if not user_ids:
                    continue
                
                # Get the thread
                thread = channel.get_thread(thread_id)
                if not thread or "[SOLVED]" in thread.name:
                    continue
                
                # Get user mentions
                user_mentions = []
                for user_id in user_ids:
                    user = bot.get_user(user_id)
                    if user:
                        user_mentions.append(user.mention)
                
                if user_mentions:
                    embed.add_field(
                        name=thread.name,
                        value=f"[Thread]({thread.jump_url})\n" + "\n".join(user_mentions),
                        inline=True
                    )
        
        # Send or update the message
        if summary_message:
            await summary_message.edit(embed=embed)
        else:
            summary_message = await channel.send(embed=embed)
            bot.assignments.set_summary_message(channel.id, summary_message.id)
        
        return summary_message
    
    except Exception as e:
        logger.error(f"Error updating summary embed: {str(e)}")