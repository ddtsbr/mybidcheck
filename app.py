import os
import json
import time
import base64
import httpx
import anthropic
import sendgrid
from sendgrid.helpers.mail import Mail
from flask import Flask, request, jsonify

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
FROM_EMAIL = "support@mybidcheck.com"
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "support@mybidcheck.com")

def download_file(url):
    response = httpx.get(url, timeout=30)
    return response.content, response.headers.get("content-type", "image/jpeg")


def analyze_quote(name, region, service_type, quote_text, file_url=None, retries=3, delay=5):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are an expert contractor quote analyzer for MyBidCheck. A homeowner named {name} in {region} has submitted a {service_type} quote for analysis.

Analyze this quote and respond ONLY with a valid JSON object — no markdown, no explanation, just raw JSON.

The JSON must have exactly this structure:
{{
  "verdict": "Fair" | "Slightly High" | "Overpriced",
  "verdictDetail": "one sentence like 'Overpriced by approximately 30%'",
  "quotedAmount": "$X,XXX",
  "typicalRange": "$X,XXX–$X,XXX",
  "lineItems": [
    {{
      "name": "line item name",
      "note": "brief note about pricing",
      "status": "Fair" | "Markup" | "Overpriced"
    }}
  ],
  "redFlags": ["red flag 1", "red flag 2"],
  "negotiationScript": "the full negotiation script the homeowner can copy and send"
}}

Here is the quote:
{quote_text}"""

    for attempt in range(retries):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = message.content[0].text.strip()
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise e


def build_email_html(name, service_type, result):
    tag_colors = {
        "Fair": ("background:#d8f3dc;color:#2d6a4f", "Fair"),
        "Markup": ("background:#fff3cd;color:#7d4e00", "Markup"),
        "Overpriced": ("background:#fde8e8;color:#9b1c1c", "Overpriced")
    }

    verdict_colors = {
        "Fair": "background:#d8f3dc;color:#2d6a4f",
        "Slightly High": "background:#fff3cd;color:#7d4e00",
        "Overpriced": "background:#fde8e8;color:#9b1c1c"
    }

    line_items_html = ""
    for item in result.get("lineItems", []):
        style, label = tag_colors.get(item["status"], ("background:#eee;color:#333", item["status"]))
        line_items_html += f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #edeae3;">
            <strong style="font-size:14px;color:#1a1a18;">{item['name']}</strong><br>
            <span style="font-size:12px;color:#8a8a84;">{item['note']}</span>
          </td>
          <td style="padding:10px 16px;border-bottom:1px solid #edeae3;text-align:right;white-space:nowrap;">
            <span style="font-size:11px;font-weight:500;padding:3px 10px;border-radius:20px;{style}">{label}</span>
          </td>
        </tr>"""

    red_flags_html = ""
    for flag in result.get("redFlags", []):
        red_flags_html += f'<li style="color:#9b1c1c;font-size:14px;margin-bottom:6px;">{flag}</li>'

    verdict_style = verdict_colors.get(result.get("verdict", "Fair"), "background:#eee;color:#333")

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f7f5f0;font-family:'DM Sans',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:32px 16px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- Header -->
  <tr><td style="background:#1a1a18;padding:24px;text-align:center;border-radius:10px 10px 0 0;">
    <span style="font-family:Georgia,serif;font-size:26px;color:#fff;">My<span style="color:#c85a1e;">Bid</span>Check</span>
  </td></tr>

  <!-- Body -->
  <tr><td style="background:#fff;padding:32px;border-radius:0 0 10px 10px;">

    <p style="font-size:16px;color:#4a4a46;margin:0 0 20px;">Hi <strong style="color:#1a1a18;">{name}</strong>,</p>
    <p style="font-size:16px;color:#4a4a46;margin:0 0 24px;">Your quote analysis is ready. Here's what we found:</p>

    <!-- Verdict -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f5f0;border-radius:10px;margin-bottom:24px;">
      <tr>
        <td style="padding:16px;">
          <strong style="font-size:17px;color:#1a1a18;display:block;margin-bottom:4px;">{service_type}</strong>
          <span style="font-size:13px;color:#8a8a84;">Quote submitted: {result.get('quotedAmount', 'N/A')} &nbsp;·&nbsp; Typical range: {result.get('typicalRange', 'N/A')}</span>
        </td>
        <td style="padding:16px;text-align:right;white-space:nowrap;">
          <span style="font-size:12px;font-weight:500;padding:5px 12px;border-radius:20px;{verdict_style}">{result.get('verdictDetail', result.get('verdict', ''))}</span>
        </td>
      </tr>
    </table>

    <!-- Line Items -->
    <p style="font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#8a8a84;margin:0 0 8px;">Line item breakdown</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #edeae3;border-radius:10px;overflow:hidden;margin-bottom:24px;">
      {line_items_html}
    </table>

    <!-- Red Flags -->
    {'<p style="font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#8a8a84;margin:0 0 8px;">Red flags</p><div style="background:#fde8e8;border-radius:10px;padding:12px 16px;margin-bottom:24px;"><ul style="margin:0;padding-left:20px;">' + red_flags_html + '</ul></div>' if result.get('redFlags') else ''}

    <!-- Script -->
    <p style="font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#8a8a84;margin:0 0 8px;">Your negotiation script</p>
    <div style="background:#f7f5f0;border-left:4px solid #c85a1e;border-radius:0 10px 10px 0;padding:16px 20px;margin-bottom:24px;">
      <p style="font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#c85a1e;margin:0 0 8px;">Copy and send this to your contractor</p>
      <p style="font-family:Georgia,serif;font-style:italic;font-size:16px;color:#1a1a18;line-height:1.65;margin:0;">{result.get('negotiationScript', '')}</p>
    </div>

    <!-- Disclaimer -->
    <p style="font-size:12px;color:#8a8a84;line-height:1.6;background:#f7f5f0;border-radius:8px;padding:12px 16px;margin-bottom:24px;">This report is for informational purposes only. Price ranges are estimates based on available regional data and may vary. MyBidCheck is not a licensed contractor or financial advisor.</p>

    <p style="font-size:14px;color:#4a4a46;">Questions? Reply to this email or contact <a href="mailto:support@mybidcheck.com" style="color:#c85a1e;">support@mybidcheck.com</a></p>

  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:20px;text-align:center;">
    <p style="font-size:12px;color:#8a8a84;margin:0;">
      &copy; 2026 MyBidCheck &nbsp;·&nbsp;
      <a href="https://mybidcheck.com/terms.html" style="color:#8a8a84;">Terms</a> &nbsp;·&nbsp;
      <a href="https://mybidcheck.com/privacy.html" style="color:#8a8a84;">Privacy</a>
    </p>
    <p style="font-size:12px;color:#8a8a84;margin:8px 0 0;">You received this because you purchased a report at MyBidCheck.com.</p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def send_fallback_email(customer_email, customer_name, service_type):
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=customer_email,
        subject=f"Your MyBidCheck Report — {service_type}",
        html_content=f"""
        <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:32px 16px;">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
        <tr><td style="background:#1a1a18;padding:24px;text-align:center;border-radius:10px 10px 0 0;">
          <span style="font-family:Georgia,serif;font-size:26px;color:#fff;">My<span style="color:#c85a1e;">Bid</span>Check</span>
        </td></tr>
        <tr><td style="background:#fff;padding:32px;border-radius:0 0 10px 10px;">
          <p style="font-size:16px;color:#4a4a46;">Hi <strong>{customer_name}</strong>,</p>
          <p style="font-size:16px;color:#4a4a46;">We received your {service_type} quote and are experiencing higher than normal demand right now. Your report will be delivered within the hour.</p>
          <p style="font-size:16px;color:#4a4a46;">We apologize for the delay. If you don't hear from us within 60 minutes, please email <a href="mailto:support@mybidcheck.com" style="color:#c85a1e;">support@mybidcheck.com</a> and we'll prioritize your report immediately.</p>
          <p style="font-size:14px;color:#8a8a84;">Thank you for your patience.</p>
        </td></tr>
        </table></td></tr></table>"""
    )
    sg.send(message)


def send_failure_alert(customer_name, customer_email, service_type, error):
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=NOTIFY_EMAIL,
        subject=f"FAILED REPORT — Action needed: {customer_name} ({service_type})",
        html_content=f"""
        <p><strong style="color:red;">Report generation failed after 3 retries!</strong></p>
        <p>Customer: {customer_name} ({customer_email})</p>
        <p>Service: {service_type}</p>
        <p>Error: {error}</p>
        <p>The customer has been sent a delay notice. Please process their report manually ASAP.</p>
        """
    )
    sg.send(message)
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    html = build_email_html(customer_name, service_type, result)

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=customer_email,
        subject=f"Your MyBidCheck Report — {service_type}",
        html_content=html
    )
    sg.send(message)


def send_notification_email(customer_name, customer_email, service_type, result):
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=NOTIFY_EMAIL,
        subject=f"New Report Sent — {customer_name} ({service_type})",
        html_content=f"""
        <p><strong>New report delivered!</strong></p>
        <p>Customer: {customer_name} ({customer_email})</p>
        <p>Service: {service_type}</p>
        <p>Verdict: {result.get('verdictDetail', '')}</p>
        <p>Quoted: {result.get('quotedAmount', '')} | Typical: {result.get('typicalRange', '')}</p>
        """
    )
    sg.send(message)


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        answers = data.get("form_response", {}).get("answers", [])
        definition = data.get("form_response", {}).get("definition", {})
        fields = definition.get("fields", [])

        field_map = {}
        for i, field in enumerate(fields):
            if i < len(answers):
                field_map[field.get("title", "").lower()] = answers[i]

        def get_answer(answer):
            if not answer:
                return ""
            atype = answer.get("type")
            if atype == "text":
                return answer.get("text", "")
            if atype == "email":
                return answer.get("email", "")
            if atype == "choice":
                return answer.get("choice", {}).get("label", "")
            return str(answer.get(atype, ""))

        customer_name = ""
        customer_email = ""
        region = ""
        service_type = ""
        quote_text = ""

        for title, answer in field_map.items():
            val = get_answer(answer)
            if "name" in title:
                customer_name = val
            elif "email" in title:
                customer_email = val
            elif "city" in title or "region" in title:
                region = val
            elif "service" in title or "type" in title:
                service_type = val
            elif "quote" in title or "paste" in title or "detail" in title:
                quote_text = val

        if not customer_email or not quote_text:
            return jsonify({"error": "Missing required fields"}), 400

        try:
            result = analyze_quote(customer_name, region, service_type, quote_text)
            send_report_email(customer_email, customer_name, service_type, result)
            send_notification_email(customer_name, customer_email, service_type, result)
        except Exception as analysis_error:
            print(f"Analysis failed after retries: {analysis_error}")
            send_fallback_email(customer_email, customer_name, service_type)
            send_failure_alert(customer_name, customer_email, service_type, str(analysis_error))

        return jsonify({"success": True}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def health():
    return "MyBidCheck webhook server is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
