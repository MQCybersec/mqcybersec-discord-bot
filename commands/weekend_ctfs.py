import discord
from discord.ext import commands
import logging
from util import fetch_ics, parse_ics, fetch_event_image, get_weekend_ctfs
from datetime import datetime, timedelta

# Function to get a logger
def get_logger():
    return logging.getLogger('discord_bot')

logger = get_logger()

class CTFPaginator(discord.ui.View):
    def __init__(self, ctfs, author_id, timeout=180):
        super().__init__(timeout=timeout)
        self.ctfs = ctfs
        self.author_id = author_id
        self.current_page = 0
        self.items_per_page = 3
        self.sort_by = "weight"  # Default sort by weight
        self.update_buttons()
    
    def get_max_pages(self):
        return (len(self.ctfs) - 1) // self.items_per_page + 1
    
    def update_buttons(self):
        # Enable/disable navigation buttons based on current page
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.get_max_pages() - 1
    
    def get_sorted_ctfs(self):
        if self.sort_by == "teams":
            return sorted(self.ctfs, key=lambda x: x['teams'], reverse=True)
        elif self.sort_by == "weight":
            return sorted(self.ctfs, key=lambda x: x['weight'], reverse=True)
        else:
            return self.ctfs  # Default order (as received from API)
    
    def get_current_page_embed(self):
        sorted_ctfs = self.get_sorted_ctfs()
        
        # Get next weekend's dates for the title
        today = datetime.now()
        saturday = today + timedelta(days=(5-today.weekday()) % 7)
        sunday = saturday + timedelta(days=1)
        weekend_str = f"{saturday.strftime('%B %d')} - {sunday.strftime('%B %d')}"
        
        # Create embed with current sorting information
        sort_info = {
            "default": "Default Order",
            "teams": "Teams (Highest First)",
            "weight": "Weight (Highest First)"
        }
        
        embed = discord.Embed(
            title=f"CTFs This Weekend ({weekend_str})",
            color=discord.Color.blue(),
            description=f"Sorting by: **{sort_info[self.sort_by]}** • Page {self.current_page + 1}/{self.get_max_pages()}"
        )
        
        # Get CTFs for current page
        start_idx = self.current_page * self.items_per_page
        page_ctfs = sorted_ctfs[start_idx:start_idx + self.items_per_page]
        
        # Add fields for each CTF on the current page
        for i, ctf in enumerate(page_ctfs, start_idx + 1):
            embed.add_field(
                name=f"{i}. {ctf['name']}",
                value=f"Format: {ctf['format']}\n"
                      f"Teams Registered: {ctf['teams']}\n"
                      f"Weight: {ctf['weight']}\n"
                      f"[CTFtime Link]({ctf['url']})",
                inline=False
            )
        
        # Add footer with total count
        embed.set_footer(text=f"Total CTFs this weekend: {len(sorted_ctfs)}")
        
        return embed
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only allow the original command author to use the buttons
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who ran this command can use these buttons.", ephemeral=True)
            return False
        return True
    
    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)
    
    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.get_max_pages() - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)
    
    @discord.ui.button(label="Sort by Teams", style=discord.ButtonStyle.secondary)
    async def sort_teams_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.sort_by = "teams"
        self.current_page = 0  # Reset to first page when sorting
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)
    
    @discord.ui.button(label="Sort by Weight", style=discord.ButtonStyle.secondary)
    async def sort_weight_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.sort_by = "weight"
        self.current_page = 0  # Reset to first page when sorting
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)

def setup(bot, guild_id, check_permissions):
    @bot.tree.command(
        name="ctf_weekend",
        description="Show CTFs happening this weekend with pagination and sorting options",
        guild=discord.Object(id=guild_id)
    )
    async def weekend_ctfs(interaction: discord.Interaction):
        required_permissions = ['view_channel', 'send_messages', 'embed_links']
        
        # Check permissions
        perm_check = check_permissions(interaction.guild, interaction.guild.me, required_permissions)
        missing_perms = [perm for perm, has_perm in perm_check.items() if not has_perm]
        
        if missing_perms:
            logger.error(f"Missing permissions for weekend_ctfs command: {', '.join(missing_perms)}")
            await interaction.response.send_message(
                f"Bot is missing required permissions: {', '.join(missing_perms)}", 
                ephemeral=True
            )
            return
        
        logger.info(f"Command 'weekend_ctfs' used by {interaction.user.name}#{interaction.user.discriminator} (ID: {interaction.user.id})")
        
        try:
            await interaction.response.defer()
            ctfs = await get_weekend_ctfs(logger)
            
            if not ctfs:
                await interaction.followup.send("No CTFs found for this weekend!")
                return
            
            # Create and send the paginated view
            paginator = CTFPaginator(ctfs, interaction.user.id)
            await interaction.followup.send(embed=paginator.get_current_page_embed(), view=paginator)
            
        except Exception as e:
            logger.error(f"Error in weekend_ctfs command: {str(e)}")
            await interaction.followup.send(f"Error fetching weekend CTFs: {str(e)}")