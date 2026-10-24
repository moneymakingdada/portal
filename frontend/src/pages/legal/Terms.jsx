import { Link } from "react-router-dom";
import { APP_NAME } from "../../config";
import { COMPANY } from "../../lib/legal";
import LegalLayout, { ContactDetails } from "./LegalLayout";

const sections = [
  {
    id: "agreement",
    title: "Who these terms are between",
    body: (
      <>
        <p>
          These terms are an agreement between you and {COMPANY.name} (“we”, “us”) about your use of {APP_NAME}, our service
          for sending one-time verification codes and other text messages (SMS) in Ghana. By creating an account you agree
          to these terms and to our <Link to="/privacy">Privacy Policy</Link>. If you don't agree, please don't create an account.
        </p>
        <p>
          If you sign up for a business, you confirm that you have the authority to accept these terms on its behalf, and
          “you” then means that business as well as you.
        </p>
      </>
    ),
  },
  {
    id: "eligibility",
    title: "Who can use the service",
    body: (
      <p>
        You must be at least 18 and able to enter into a contract. You need a Ghana mobile number that you can receive a
        verification code on. {APP_NAME} is meant for businesses, developers and organisations, not for sending personal
        messages.
      </p>
    ),
  },
  {
    id: "account",
    title: "Your account and API keys",
    body: (
      <>
        <p>Give us accurate details and keep them up to date. Keep your password and your API keys secret.</p>
        <p>
          You are responsible for everything done with your account and your keys, including messages sent and money spent.
          If you think either has been exposed, revoke the key in your dashboard and tell us straight away.
        </p>
      </>
    ),
  },
  {
    id: "service",
    title: "What the service does",
    body: (
      <>
        <p>
          {APP_NAME} lets you send verification codes, and thank-you, welcome, holiday, birthday and custom messages to your
          customers, one at a time, through our API or dashboard, or to a list at once with Bulk SMS.
        </p>
        <ul>
          <li>Test keys send no SMS and cost nothing. Live keys send real messages and are charged to your wallet.</li>
          <li>
            Messages travel through SMS providers and the mobile networks (MTN, Telecel, AirtelTigo and others). We can't
            promise that a message will arrive, or when. A message is only shown as “Delivered” when the provider reports it.
          </li>
          <li>We may improve, change or retire features. Where we can, we'll tell you first if a change affects you.</li>
        </ul>
      </>
    ),
  },
  {
    id: "payments",
    title: "Your wallet, prices and payments",
    body: (
      <>
        <p>
          {APP_NAME} is prepaid. You add money to your wallet in Ghana cedis (GHS) and each message you send is charged
          against it. Prices are shown in your dashboard. A long message, or one with characters outside the basic alphabet,
          is split into more than one SMS part and costs more.
        </p>
        <ul>
          <li>Payments are taken by Paystack. We never see or store your card details or Mobile Money PIN.</li>
          <li>A message is charged when it is accepted for sending. If the provider then rejects it, we refund it to your wallet automatically.</li>
          <li>Wallet credit is not cash and can't be withdrawn. Unused credit is not refundable, except where the law requires it or we agree otherwise.</li>
          <li>A daily spend limit protects your wallet from mistakes and runaway code. It is set on your account and we may change it.</li>
          <li>Any free starter credit is a gift: we may change or stop offering it.</li>
        </ul>
      </>
    ),
  },
  {
    id: "messages",
    title: "Your messages and your contacts",
    body: (
      <>
        <p>
          You are responsible for the content of your messages and for who you send them to. In particular you must:
        </p>
        <ul>
          <li>have the right to message each person (their consent, or another lawful reason) and the right to give us their details;</li>
          <li>say who you are in your messages, and not mislead anyone;</li>
          <li>stop messaging anyone who asks you to. Add them to your opt-out list. We block sends to numbers on that list, but it is up to you to put them there;</li>
          <li>follow the laws that apply to you, including the Data Protection Act, 2012 (Act 843) and the rules of the National Communications Authority and the mobile networks.</li>
        </ul>
        <p>
          For the personal data of your own customers and contacts, you decide why and how it is used and we handle it on
          your behalf. Our <Link to="/privacy">Privacy Policy</Link> explains how.
        </p>
      </>
    ),
  },
  {
    id: "rules",
    title: "What you must not do",
    body: (
      <>
        <p>You must not use {APP_NAME} to:</p>
        <ul>
          <li>send spam, or messages to people who haven't agreed to hear from you;</li>
          <li>deceive or defraud anyone, including phishing, scams, fake prizes or pretending to be a bank, a government body, a mobile network or another person or business;</li>
          <li>send unlawful, threatening, abusive, hateful or sexually explicit content;</li>
          <li>flood a phone number with codes or messages, or use verification codes to harass someone;</li>
          <li>send messages that break the rules of a network or provider we depend on;</li>
          <li>get around our limits, security or opt-out checks, probe or attack the service, or resell it without our written agreement.</li>
        </ul>
      </>
    ),
  },
  {
    id: "sender-ids",
    title: "Sender IDs",
    body: (
      <>
        <p>
          A sender ID is the name your customers see instead of a phone number. To request one you upload a signed letter of
          authorization and a Ghana Card (individuals) or business registration certificate (businesses). Everything you
          upload must be true and belong to you.
        </p>
        <p>
          We review requests, and the networks must also approve the name, which can take a few days. Approval is not
          guaranteed. We may refuse or withdraw a sender ID, for example if it imitates a bank, government body or mobile
          network, or if the paperwork turns out to be false. Until a sender ID is approved, messages go out under our default name.
        </p>
      </>
    ),
  },
  {
    id: "suspension",
    title: "Suspending or closing your account",
    body: (
      <>
        <p>
          We may suspend or close your account, with or without notice, if you break these terms, if we think it is needed to
          prevent fraud, abuse or harm, if a network, provider or authority requires it, or if the law requires it. Where
          it is reasonable we'll tell you why.
        </p>
        <p>You can stop using {APP_NAME} at any time and ask us to close your account. Sections that by their nature should continue to apply will do so after closure.</p>
      </>
    ),
  },
  {
    id: "ownership",
    title: "Ownership",
    body: (
      <p>
        We own {APP_NAME}, including its software, design and name. You keep ownership of your messages, contact lists and
        documents. You give us permission to store and use them only as needed to run the service for you, as described in
        our Privacy Policy.
      </p>
    ),
  },
  {
    id: "liability",
    title: "Our responsibility to you",
    body: (
      <>
        <p>
          The service is provided “as is”. We work hard to keep it running but we can't promise it will always be available
          or error-free, and we are not responsible for the mobile networks, SMS providers or payment providers that it depends on.
        </p>
        <p>
          Nothing in these terms limits liability that the law doesn't allow us to limit. Beyond that, we are not liable for
          indirect or consequential loss, lost profit or lost business, or for messages that are delayed or not delivered.
          Our total liability for any claim is limited to the amount you paid us in the three months before it arose.
        </p>
        <p>
          You agree to cover us for claims and costs that come from your messages, your contact lists, or your breach of these terms.
        </p>
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes to these terms",
    body: (
      <p>
        We may update these terms. The date above shows the current version. If a change matters, we'll tell you in your
        dashboard or by email before it applies. If you keep using {APP_NAME} after that, you accept the new terms. If you
        don't, you can close your account.
      </p>
    ),
  },
  {
    id: "law",
    title: "Governing law",
    body: (
      <p>
        These terms are governed by the laws of Ghana. If we have a disagreement, let's try to sort it out together first. If
        we can't, the courts of Ghana will decide it.
      </p>
    ),
  },
  {
    id: "contact",
    title: "Contact us",
    body: (
      <>
        <p>Questions about these terms?</p>
        <ContactDetails />
      </>
    ),
  },
];

export default function Terms() {
  return (
    <LegalLayout
      title="Terms of Service"
      summary={`Use ${APP_NAME} honestly, only message people you're allowed to, keep your keys safe, and pay for what you send. We'll do our best to deliver, but the networks decide the rest.`}
      sections={sections}
    />
  );
}
