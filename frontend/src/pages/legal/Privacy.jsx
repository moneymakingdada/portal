import { Link } from "react-router-dom";
import { APP_NAME } from "../../config";
import { COMPANY } from "../../lib/legal";
import LegalLayout, { ContactDetails } from "./LegalLayout";

const sections = [
  {
    id: "who",
    title: "Who we are",
    body: (
      <>
        <p>
          {COMPANY.name} runs {APP_NAME}. This policy explains what personal information we collect, why, who we share it
          with, and the choices you have. It applies to people who create an account and to people whose phone numbers are
          messaged through {APP_NAME}.
        </p>
        <p>We play two roles:</p>
        <ul>
          <li>
            <strong>For your account</strong> (your name, email, phone number, sign-in and billing details) we decide why
            and how the data is used. We are the “data controller”.
          </li>
          <li>
            <strong>For the people you message</strong> (your customers' phone numbers, names, birth dates and the messages
            themselves) you decide why and how the data is used and we handle it on your behalf. We are the “data
            processor”, and you are responsible for having the right to message them.
          </li>
        </ul>
        {COMPANY.dpcRegistration && (
          <p>We are registered with the Data Protection Commission of Ghana (registration number {COMPANY.dpcRegistration}).</p>
        )}
      </>
    ),
  },
  {
    id: "collect",
    title: "What we collect",
    body: (
      <>
        <p><strong>When you sign up and use your account</strong></p>
        <ul>
          <li>Your name, email address, mobile number and business or app name.</li>
          <li>Your password, stored only as a one-way hash, so nobody (including us) can read it.</li>
          <li>The verification code we text you. It is short-lived, and stored only as a hash.</li>
          <li>The date and version of the terms you agreed to.</li>
          <li>Your API keys (stored hashed, with a short prefix we use to find them) and how they are used.</li>
        </ul>
        <p><strong>About the messages you send</strong></p>
        <ul>
          <li>The recipient's phone number, the sender name, when it was sent, its status, its price and any error. For customer messages, the text of the message. Verification codes are stored masked.</li>
          <li>The contacts you add or upload: names, phone numbers, emails, birth dates and notes, and your opt-out list.</li>
          <li>Bulk lists you paste or upload. The numbers and details are kept only while the batch is running, then cleared (the individual messages stay in your message log).</li>
        </ul>
        <p><strong>Sender ID paperwork</strong></p>
        <ul>
          <li>The signed letter of authorization and the Ghana Card or business registration certificate you upload, which may contain personal details such as your photo, ID number and date of birth.</li>
        </ul>
        <p><strong>Payments</strong></p>
        <ul>
          <li>The amount, date, status and reference of each top-up. Paystack collects your card or Mobile Money details directly. We never receive them.</li>
        </ul>
        <p><strong>Technical data</strong></p>
        <ul>
          <li>Your IP address and request details, used to limit abuse and keep the service secure, and cookies that keep you signed in (see below).</li>
        </ul>
      </>
    ),
  },
  {
    id: "use",
    title: "How we use it",
    body: (
      <>
        <ul>
          <li>To create and secure your account, and to check that your phone number is yours.</li>
          <li>To send the messages you ask us to send, and to track whether they were delivered.</li>
          <li>To charge your wallet, process top-ups and refunds, and keep a record of every movement of money.</li>
          <li>To review sender ID requests with the SMS provider and the networks.</li>
          <li>To prevent fraud, spam and misuse, including rate limits and daily spend limits.</li>
          <li>To give you support, and to send you service messages such as a welcome text or the outcome of a sender ID request.</li>
          <li>To meet our legal obligations and to protect our rights.</li>
        </ul>
        <p>
          When a new account or sender ID request arrives, our staff are notified by SMS, including the name, business name,
          phone number and email involved, so that they can review it. We don't sell your personal information and we don't
          use it for advertising.
        </p>
      </>
    ),
  },
  {
    id: "share",
    title: "Who we share it with",
    body: (
      <>
        <p>We share personal information only where it is needed to run the service:</p>
        <ul>
          <li><strong>SMS providers and mobile networks</strong>, such as Arkesel and Dexatel and the networks they use (MTN, Telecel, AirtelTigo), who receive the recipient's number, the sender name and the message text in order to deliver it.</li>
          <li><strong>Paystack</strong>, which processes top-up payments.</li>
          <li><strong>Our hosting and infrastructure providers</strong>, who store and process data for us under their own security commitments.</li>
          <li><strong>Authorities and advisers</strong>, where the law requires it or to protect our rights, for example to a regulator, a court, or our lawyers.</li>
        </ul>
        <p>If our business is ever sold or merged, your information may move to the new owner, who must keep honouring this policy.</p>
      </>
    ),
  },
  {
    id: "transfers",
    title: "Where data is stored",
    body: (
      <p>
        Our providers may store or process data outside Ghana. Where they do, we choose providers with appropriate security
        and rely on them to protect it in line with the Data Protection Act, 2012 (Act 843).
      </p>
    ),
  },
  {
    id: "keep",
    title: "How long we keep it",
    body: (
      <>
        <ul>
          <li>A sign-up that is never verified is deleted after 10 minutes. Verification codes expire within minutes.</li>
          <li>Account details are kept while your account is open.</li>
          <li>Message logs and wallet records are kept while your account is open, and afterwards for as long as we need them for billing, disputes, fraud prevention and the law.</li>
          <li>Sender ID documents are kept while the request or sender ID is active, and for a reasonable period after so we can answer questions from the networks.</li>
          <li>When we no longer need information, we delete it or make it anonymous.</li>
        </ul>
      </>
    ),
  },
  {
    id: "security",
    title: "How we protect it",
    body: (
      <p>
        Passwords and codes are hashed. Uploaded documents are visible only to our staff, who can only download them. Access
        is limited to people who need it, connections are encrypted, and we rate-limit sign-ins and messages. No system is
        completely secure, so please use a strong, unique password and keep your API keys private.
      </p>
    ),
  },
  {
    id: "rights",
    title: "Your rights",
    body: (
      <>
        <p>Under the Data Protection Act, 2012 (Act 843) you can:</p>
        <ul>
          <li>ask whether we hold personal information about you, and get a copy;</li>
          <li>ask us to correct information that is wrong or out of date;</li>
          <li>ask us to delete information we no longer need, or to stop using it;</li>
          <li>object to your information being used for direct marketing;</li>
          <li>withdraw consent you have given, which doesn't affect what we did before.</li>
        </ul>
        <p>
          To use any of these, contact us (below). We may need to check who you are first. If you're unhappy with our
          answer, you can complain to the Data Protection Commission of Ghana.
        </p>
      </>
    ),
  },
  {
    id: "recipients",
    title: "If you received a message through " + APP_NAME,
    body: (
      <p>
        A business sent you that message, and it is responsible for why you got it. Ask that business to stop messaging you
        and to add your number to its opt-out list; we block sends to numbers on that list. You can also contact us and we
        will pass your request on, and help you exercise your rights over any information we hold about you.
      </p>
    ),
  },
  {
    id: "cookies",
    title: "Cookies and browser storage",
    body: (
      <p>
        We use only what the site needs to work: a session cookie that keeps you signed in, a security cookie that protects
        forms from forgery, and temporary browser storage that lets you resume sign-up if you refresh the page. We don't use
        advertising or tracking cookies.
      </p>
    ),
  },
  {
    id: "children",
    title: "Children",
    body: <p>{APP_NAME} is not for anyone under 18, and we don't knowingly collect information from children for our own use.</p>,
  },
  {
    id: "changes",
    title: "Changes to this policy",
    body: (
      <p>
        We may update this policy. The date above shows the current version. If a change matters, we'll tell you in your
        dashboard or by email. See also our <Link to="/terms">Terms of Service</Link>.
      </p>
    ),
  },
  {
    id: "contact",
    title: "Contact us",
    body: (
      <>
        <p>Questions, or want to use your rights?</p>
        <ContactDetails />
      </>
    ),
  },
];

export default function Privacy() {
  return (
    <LegalLayout
      title="Privacy Policy"
      summary={`We collect what we need to run your account and deliver your messages, share it only with the providers that make that possible, never sell it, and you can ask to see, correct or delete it.`}
      sections={sections}
    />
  );
}
