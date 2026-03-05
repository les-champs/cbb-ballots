import os
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =============================
# Configuration
# =============================
base_url = "https://www.cbbpoll.net"
logo_folder = "logos"
browser_choice = "safari"
debug = True
debug_limit = 3

os.makedirs(logo_folder, exist_ok=True)

# =============================
# Launch Browser
# =============================
if browser_choice.lower() == "safari":
    driver = webdriver.Safari()
elif browser_choice.lower() == "chrome":
    driver = webdriver.Chrome()
else:
    raise ValueError("Unsupported browser")

driver.get(base_url)

WebDriverWait(driver,10).until(
    EC.presence_of_element_located((By.TAG_NAME,"h2"))
)

# =============================
# Preview Image Generator
# =============================
def generate_preview_image(title, user_rank_data, usernames, output_file):

    width = 1200
    height = 630

    img = Image.new("RGB",(width,height),(245,245,245))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("Arial.ttf",60)
        font_user = ImageFont.truetype("Arial.ttf",22)
    except:
        font_title = ImageFont.load_default()
        font_user = ImageFont.load_default()

    draw.text((60,40),title,fill=(20,20,20),font=font_title)

    start_x = 220
    start_y = 160
    cell = 40

    preview_rows = min(len(user_rank_data),8)
    preview_cols = 10

    for r in range(preview_rows):

        username = usernames[r][:12]
        draw.text((40,start_y + r*cell + 8),username,fill=(30,30,30),font=font_user)

        ballot = user_rank_data[r]

        for c in range(preview_cols):

            rank = str(c+1)
            logo_path, team_name = ballot.get(rank,(None,None))

            if logo_path and os.path.exists(logo_path):

                logo = Image.open(logo_path).convert("RGBA")
                logo = logo.resize((32,32))

                x = start_x + c*cell
                y = start_y + r*cell

                img.paste(logo,(x,y),logo)

    img.save(output_file)

# =============================
# Collect Ballot URLs
# =============================
def get_ballot_urls(section_name):

    urls = []
    headers = driver.find_elements(By.TAG_NAME,"h2")

    for i,header in enumerate(headers):

        if header.text.strip() != section_name:
            continue

        all_links = driver.find_elements(By.XPATH,"//a[contains(@href,'/ballots/')]")

        header_y = header.location['y']
        next_header_y = headers[i+1].location['y'] if i+1 < len(headers) else None

        for link in all_links:

            link_y = link.location['y']

            if link_y > header_y and (next_header_y is None or link_y < next_header_y):

                href = link.get_attribute("href")

                if href:
                    urls.append(href)

        break

    return list(dict.fromkeys(urls))


official_urls = get_ballot_urls("Official Ballots")
provisional_urls = get_ballot_urls("Provisional Ballots")

if debug:
    official_urls = official_urls[:debug_limit]
    provisional_urls = provisional_urls[:debug_limit]

print(f"Official ballots: {len(official_urls)}")
print(f"Provisional ballots: {len(provisional_urls)}")

# =============================
# Build Table
# =============================
def build_comparison_table(ballot_urls):

    usernames = []
    user_logos = []
    user_rank_data = []

    for url in ballot_urls:

        print("Scraping",url)
        driver.get(url)

        WebDriverWait(driver,10).until(
            EC.presence_of_element_located((By.TAG_NAME,"table"))
        )

        try:
            user_link = driver.find_element(By.CSS_SELECTOR,"a[href^='/users/']")
            username_text = user_link.text.strip()
            username = username_text.replace("'s","").strip()
        except:
            username = "Unknown"

        usernames.append(username)
        user_logos.append(None)

        rank_map = {str(i):(None,None) for i in range(1,26)}

        table = driver.find_element(By.TAG_NAME,"table")
        rows = table.find_elements(By.TAG_NAME,"tr")

        for row in rows:

            cells = row.find_elements(By.TAG_NAME,"td")

            if len(cells) < 2:
                continue

            rank = cells[0].get_attribute("innerText").strip()
            team_name = cells[1].get_attribute("innerText").strip()

            team_safe = team_name.replace(" ","")
            logo_path = os.path.join(logo_folder,f"{team_safe}.png")

            if not os.path.exists(logo_path):

                logo_url = f"https://www.cbbpoll.net/_next/image?url=/static/D1/{team_safe}.png&w=64&q=75"

                try:
                    r = requests.get(logo_url)

                    if r.status_code == 200:

                        with open(logo_path,"wb") as f:
                            f.write(r.content)
                except:
                    pass

            if rank in rank_map:
                rank_map[rank] = (logo_path,team_name)

        user_rank_data.append(rank_map)

    # Build HTML
    header_html = "<thead><tr><th>User</th>"

    for rank in range(1,26):
        header_html += f"<th>{rank}</th>"

    header_html += "</tr></thead>"

    rows_html = "<tbody>"

    for i,username in enumerate(usernames):

        rows_html += "<tr>"

        ballot_url = ballot_urls[i]

        rows_html += f'<td><a href="{ballot_url}" target="_blank" class="cell-link">{username}</a></td>'

        for rank in range(1,26):

            logo_path,team_name = user_rank_data[i].get(str(rank),(None,None))

            if logo_path:

                team_id = team_name.lower().replace(" ","_")

                rows_html += f'<td><img src="{logo_path}" class="logo team-logo" data-team="{team_id}"></td>'

            else:

                rows_html += "<td></td>"

        rows_html += "</tr>"

    rows_html += "</tbody>"

    table_html = f"""
<table>
{header_html}
{rows_html}
</table>
"""

    return table_html, user_rank_data, usernames


# =============================
# HTML Template
# =============================
base_html_template = """
<html>
<head>

<title>{title}</title>

<meta property="og:title" content="{title}">
<meta property="og:description" content="Comparison of NCAA ballots from users">
<meta property="og:image" content="{preview}">
<meta property="og:type" content="website">
<meta name="twitter:card" content="summary_large_image">

<style>

body {{
font-family:sans-serif;
margin:20px;
background:#f8f8f8;
}}

table {{
border-collapse:collapse;
table-layout:fixed;
width:100%;
}}

th,td {{
border:1px solid #3B3B3B;
text-align:center;
padding:4px;
}}

th:first-child,td:first-child {{
width:150px;
}}

.logo {{
width:25px;
display:block;
margin:auto;
cursor:pointer;
}}

.logo:hover {{
transform:scale(1.3);
transition:0.2s;
}}

.cell-link {{
display:block;
text-decoration:none;
color:inherit;
}}

thead th {{
position:sticky;
top:0;
background:white;
z-index:2;
}}

th:nth-child(5),td:nth-child(5),
th:nth-child(9),td:nth-child(9),
th:nth-child(13),td:nth-child(13),
th:nth-child(17),td:nth-child(17),
th:nth-child(21),td:nth-child(21) {{
border-right:3px solid #0D0D0D;
}}

.team-highlight-1 {{ outline:3px solid #ffcc00 }}
.team-highlight-2 {{ outline:3px solid #66ccff }}
.team-highlight-3 {{ outline:3px solid #ff6666 }}
.team-highlight-4 {{ outline:3px solid #33cc33 }}
.team-highlight-5 {{ outline:3px solid #cc66ff }}
.team-highlight-6 {{ outline:3px solid #ff9966 }}
.team-highlight-7 {{ outline:3px solid #ff3399 }}
.team-highlight-8 {{ outline:3px solid #339966 }}
.team-highlight-9 {{ outline:3px solid #3366cc }}
.team-highlight-10 {{ outline:3px solid #999933 }}

</style>
</head>

<body>

<h1>{title}</h1>

{table}

<script>

const highlightClasses=[
"team-highlight-1","team-highlight-2","team-highlight-3","team-highlight-4",
"team-highlight-5","team-highlight-6","team-highlight-7","team-highlight-8",
"team-highlight-9","team-highlight-10"
]

document.querySelectorAll(".team-logo").forEach(logo=>{{

logo.addEventListener("click",()=>{{

const team=logo.dataset.team
const teamElements=document.querySelectorAll(`.team-logo[data-team="${{team}}"]`)

const already=[...teamElements].find(el=>highlightClasses.some(c=>el.classList.contains(c)))

if(already){{
teamElements.forEach(el=>highlightClasses.forEach(c=>el.classList.remove(c)))
}}
else{{

const used=[...document.querySelectorAll(".team-logo")]
.flatMap(el=>highlightClasses.filter(c=>el.classList.contains(c)))

const color=highlightClasses.find(c=>!used.includes(c))

if(color) teamElements.forEach(el=>el.classList.add(color))

}}

}})

}})

</script>

</body>
</html>
"""

# =============================
# Generate Pages
# =============================
official_table, official_rank_data, official_users = build_comparison_table(official_urls)

generate_preview_image(
    "Official Ballots",
    official_rank_data,
    official_users,
    "official_preview.png"
)

with open("official_ballots.html","w") as f:
    f.write(base_html_template.format(
        title="Official Ballots",
        table=official_table,
        preview="official_preview.png"
    ))

print("Saved official_ballots.html")

provisional_table, provisional_rank_data, provisional_users = build_comparison_table(provisional_urls)

generate_preview_image(
    "Provisional Ballots",
    provisional_rank_data,
    provisional_users,
    "provisional_preview.png"
)

with open("provisional_ballots.html","w") as f:
    f.write(base_html_template.format(
        title="Provisional Ballots",
        table=provisional_table,
        preview="provisional_preview.png"
    ))

print("Saved provisional_ballots.html")

driver.quit()