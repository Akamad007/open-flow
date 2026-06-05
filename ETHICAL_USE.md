# Ethical Use & AI Disclosure

OpenFlow can generate photorealistic video and can synthesize a specific
person's face/identity into generated scenes (via the optional InstantID
pipeline). These capabilities can be misused. By using OpenFlow you agree to the
following terms, in addition to the [LICENSE](LICENSE).

## You must NOT use OpenFlow to

- Create imagery or video of a **real, identifiable person without their
  explicit, informed consent** — this includes face-swapping, "deepfakes," or
  putting words/actions onto a real person.
- Generate content depicting **minors** in any sexual or exploitative context.
- Produce **non-consensual intimate imagery**.
- Create material intended to **defraud, defame, harass, impersonate, or spread
  disinformation** (e.g. fake statements by public figures).
- Violate the license of any underlying model (see
  [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)). Several model licenses
  independently prohibit impersonation and illegal content.

## You must

- **Obtain consent** before using any real person's likeness or voice reference.
- **Disclose** that output is AI-generated when publishing or sharing it.
- Comply with the laws of your jurisdiction. Synthetic-media, biometric, and
  publicity-rights laws vary widely and are evolving.

## Identity synthesis is gated

The identity/face pipeline (`IDENTITY_PROVIDER_ENABLED`) involves real-likeness
risk. For non-personal/demo use you can leave it on; for any deployment that
accepts third-party input, set `REQUIRE_CONSENT_ACKNOWLEDGMENT=true` so an
explicit consent acknowledgement is required before a likeness is used, and keep
an audit trail of what reference images were supplied.

## Content moderation

OpenFlow ships **without** automated content moderation. Prompts and reference
images are not screened. If you operate it as a service, you are responsible for
adding moderation appropriate to your users and jurisdiction. See
[CONTENT_SAFETY.md](CONTENT_SAFETY.md).

## No warranty / no liability

OpenFlow is provided "as is" (see LICENSE). The authors are not responsible for
content you generate or how you use it. **You** are.

If you believe OpenFlow is being used to harm someone, contact
**akashdeshpande2000@gmail.com**.
