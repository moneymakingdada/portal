import { publicApiBase } from "../config";

/** Code samples shown on the landing page and in the dashboard quickstart. */
export function otpSamples({ key = "sk_test_YOUR_KEY", base = publicApiBase() } = {}) {
  return [
    {
      id: "curl",
      label: "curl",
      code: `# 1. Send a code
curl -X POST ${base}/otp/send \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"to": "024 123 4567", "purpose": "login"}'

# -> {"request_id": "6f1c…", "expires_at": "…", "to": "+233241234567"}

# 2. Check what the user typed
curl -X POST ${base}/otp/verify \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"request_id": "6f1c…", "code": "123456"}'

# -> {"verified": true}`,
    },
    {
      id: "js",
      label: "JavaScript",
      code: `const API = "${base}";
const headers = {
  Authorization: "Bearer ${key}",
  "Content-Type": "application/json",
};

// 1. Send a code
const sent = await fetch(\`\${API}/otp/send\`, {
  method: "POST",
  headers,
  body: JSON.stringify({ to: "024 123 4567", purpose: "login" }),
}).then((r) => r.json());

// 2. Check what the user typed
const result = await fetch(\`\${API}/otp/verify\`, {
  method: "POST",
  headers,
  body: JSON.stringify({ request_id: sent.request_id, code: "123456" }),
}).then((r) => r.json());

console.log(result.verified); // true`,
    },
    {
      id: "python",
      label: "Python",
      code: `import requests

API = "${base}"
headers = {"Authorization": "Bearer ${key}"}

# 1. Send a code
sent = requests.post(
    f"{API}/otp/send",
    headers=headers,
    json={"to": "024 123 4567", "purpose": "login"},
    timeout=10,
).json()

# 2. Check what the user typed
result = requests.post(
    f"{API}/otp/verify",
    headers=headers,
    json={"request_id": sent["request_id"], "code": "123456"},
    timeout=10,
).json()

print(result["verified"])  # True`,
    },
  ];
}

/** Code samples for the customer-messaging API (/v1/messages/send). */
export function customerMessageSamples({ key = "sk_live_YOUR_KEY", base = publicApiBase() } = {}) {
  return [
    {
      id: "curl",
      label: "curl",
      code: `curl -X POST ${base}/messages/send \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "to": "024 123 4567",
    "category": "thank_you",
    "customer_name": "Ama",
    "amount": 45.50
  }'

# -> {"message_id": "…", "to": "+233241234567", "body": "Thank you for shopping with …", "customer_id": "…"}`,
    },
    {
      id: "js",
      label: "JavaScript",
      code: `const API = "${base}";

// After a successful checkout:
await fetch(\`\${API}/messages/send\`, {
  method: "POST",
  headers: {
    Authorization: "Bearer ${key}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    to: customer.phone,
    category: "thank_you",
    customer_name: customer.name,
    amount: order.total, // e.g. 45.50 (GHS)
  }),
});`,
    },
    {
      id: "python",
      label: "Python",
      code: `import requests

API = "${base}"
headers = {"Authorization": "Bearer ${key}"}

# After a successful checkout:
requests.post(
    f"{API}/messages/send",
    headers=headers,
    json={
        "to": customer_phone,
        "category": "thank_you",
        "customer_name": customer_name,
        "amount": order_total,  # e.g. 45.50 (GHS)
    },
    timeout=10,
)`,
    },
  ];
}
