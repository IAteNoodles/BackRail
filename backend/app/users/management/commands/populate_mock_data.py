"""
Management command to populate the database with mock data and generate
real PDF documents using reportlab.

Usage:
    python manage.py populate_mock_data
    python manage.py populate_mock_data --clear   # wipe existing data first
"""
import os
import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)
from reportlab.lib import colors

from users.models import User, Category, Document, Post, AuditLog

# ── Constants ─────────────────────────────────────────────────────────

CATEGORIES = [
    'Rolling Stock',
    'Track & Bridges',
    'Signalling & Telecom',
    'Electrical',
    'Safety',
    'General',
]

DOCUMENTS = [
    {
        'document_id': 'RDSO-RS-001',
        'name': 'Specification for Locomotives – Broad Gauge',
        'version': '4.2',
        'categories': ['Rolling Stock'],
        'sections': [
            ('1. Scope', 'This specification covers the design, manufacture, testing, and performance requirements for broad gauge diesel and electric locomotives used on Indian Railways.'),
            ('2. Design Requirements', 'Locomotives shall be designed to operate on broad gauge (1676 mm) track with a maximum axle load of 22.9 tonnes. The body structure shall withstand a compressive load of 200 tonnes at the buffer beam level.'),
            ('3. Propulsion System', 'AC-AC traction systems with IGBT-based propulsion converters are recommended. The traction motors shall have a continuous rating of not less than 850 kW per motor.'),
            ('4. Braking System', 'The locomotive shall be equipped with dynamic braking (regenerative and rheostatic), automatic air brakes, and direct brakes conforming to UIC standards.'),
            ('5. Testing & Acceptance', 'Type tests, routine tests, and commissioning tests shall be conducted as per RDSO guidelines. Speed trials up to 10% above the designed maximum speed are mandatory.'),
        ],
    },
    {
        'document_id': 'RDSO-RS-002',
        'name': 'Maintenance Manual for LHB Coaches',
        'version': '3.1',
        'categories': ['Rolling Stock'],
        'sections': [
            ('1. Purpose', 'This manual prescribes maintenance schedules and procedures for Linke Hofmann Busch (LHB) coaches deployed across Indian Railways.'),
            ('2. Periodic Overhaul (POH)', 'POH shall be carried out at intervals not exceeding 18 months or 6 lakh km, whichever is earlier. All safety-critical components must be replaced or refurbished.'),
            ('3. Bogie Maintenance', 'FIAT bogies shall be inspected for cracks using ultrasonic testing. Air spring assemblies, lateral and vertical dampers, and anti-roll bars must be tested individually.'),
            ('4. Interior Fittings', 'Upholstery, modular panels, window assemblies, and seat frames shall comply with RDSO fire safety norms (Specification No. RDSO/2020/CG-14).'),
        ],
    },
    {
        'document_id': 'RDSO-TB-001',
        'name': 'Indian Railways Permanent Way Manual',
        'version': '5.0',
        'categories': ['Track & Bridges'],
        'sections': [
            ('1. Track Standards', 'All main-line tracks shall use 60 kg 110 UTS rails on PSC sleepers with elastic fastenings. Track gauge tolerance is ±6 mm for group A routes.'),
            ('2. Ballast Specifications', 'Ballast shall be hard, durable, angular stone conforming to IRS-GE-1 specifications. Minimum ballast cushion under the sleeper shall be 250 mm for BG routes.'),
            ('3. Rail Welding', 'Flash butt welding is the preferred method for long welded rails. Thermit welding may be used for in-situ joints. All welds shall be tested ultrasonically.'),
            ('4. Curve Design', 'Super-elevation on curves shall not exceed 165 mm. Transition curves shall follow cubic parabola design. Speed restrictions apply based on degree of curvature.'),
        ],
    },
    {
        'document_id': 'RDSO-TB-002',
        'name': 'Guidelines for Bridge Inspection',
        'version': '2.3',
        'categories': ['Track & Bridges'],
        'sections': [
            ('1. Scope', 'These guidelines cover inspection procedures for steel, concrete, and masonry bridges on Indian Railways. All bridges with span > 6.1 m are included.'),
            ('2. Inspection Frequency', 'Major bridges require annual detailed inspection. Bridges over 100 years old or those with known deficiencies require bi-annual inspection.'),
            ('3. Load Rating', 'Every bridge must have a current load rating. Modified BG Loading (MBG) standard shall be used for broad gauge bridges. Heavy Mineral Loading (HM) applies to freight corridors.'),
        ],
    },
    {
        'document_id': 'RDSO-ST-001',
        'name': 'Signalling Standards for Electronic Interlocking',
        'version': '6.1',
        'categories': ['Signalling & Telecom'],
        'sections': [
            ('1. Introduction', 'Electronic Interlocking (EI) systems replace traditional relay interlocking for controlling points and signals. This document specifies requirements for EI systems.'),
            ('2. Safety Integrity Level', 'EI systems shall be designed to Safety Integrity Level 4 (SIL-4) as per IEC 62278. Vital functions must implement 2-out-of-3 or 2-out-of-2 redundancy.'),
            ('3. Object Controller', 'Object Controllers shall interface with field elements (signals, point machines, track circuits). Communication with the central processor uses Ethernet-based protocols with CRC-32 protection.'),
            ('4. Display and Control', 'A graphical display panel shall show real-time track layout, signal aspects, point positions, and track occupancy. Touch-screen operation is permissible for non-vital functions only.'),
        ],
    },
    {
        'document_id': 'RDSO-ST-002',
        'name': 'TCAS (Train Collision Avoidance System) Specification',
        'version': '1.5',
        'categories': ['Signalling & Telecom', 'Safety'],
        'sections': [
            ('1. Objective', 'TCAS is designed to prevent train collisions by providing automatic braking when two trains are on a collision course, or when a train overshoots a signal at danger.'),
            ('2. System Architecture', 'The system consists of loco-mounted equipment, stationary equipment at stations, RFID tags on track, and a network management system. GPS/IRNSS positioning with sub-metre accuracy is required.'),
            ('3. Operating Modes', 'TCAS operates in Automatic, Advisory, and Manual modes. In Automatic mode, braking is applied without driver intervention when danger thresholds are crossed.'),
        ],
    },
    {
        'document_id': 'RDSO-EL-001',
        'name': 'Specification for 25 kV AC Traction Overhead Equipment',
        'version': '3.8',
        'categories': ['Electrical'],
        'sections': [
            ('1. General', 'This specification covers the design and installation of 25 kV, 50 Hz single-phase AC overhead equipment (OHE) for electrified railway sections.'),
            ('2. Catenary System', 'Regulated catenary construction with contact wire height of 5.5 m (nominal) above rail level. Contact wire shall be hard-drawn copper or copper-alloy of 107 mm² cross-section.'),
            ('3. Mast & Foundations', 'Fabricated steel masts shall be designed for wind zone IV loading. Foundation design shall consider soil bearing capacity and seismic zone classification.'),
            ('4. Insulation Requirements', 'Post insulators, stay arm insulators, and section insulators shall have a minimum creepage distance of 25 mm/kV for polluted areas.'),
        ],
    },
    {
        'document_id': 'RDSO-EL-002',
        'name': 'Power Supply & Distribution for Traction',
        'version': '2.0',
        'categories': ['Electrical'],
        'sections': [
            ('1. Traction Sub-Station', 'Traction sub-stations shall be spaced at intervals not exceeding 70 km for 25 kV AC sections. Each sub-station shall have a capacity of at least 30 MVA.'),
            ('2. Protection Systems', 'Distance protection, over-current protection, and earth fault protection shall be provided. Auto-reclosure is mandatory with a dead time of 3 seconds.'),
            ('3. SCADA Integration', 'All traction electrical equipment shall be monitored via SCADA. Remote control of circuit breakers and isolators is mandatory.'),
        ],
    },
    {
        'document_id': 'RDSO-SF-001',
        'name': 'Fire Safety Standards for Rolling Stock',
        'version': '2.5',
        'categories': ['Safety', 'Rolling Stock'],
        'sections': [
            ('1. Material Standards', 'All materials used in coach interiors shall meet fire resistance standards as per IS 11871 and EN 45545-2. Halogen-free materials are preferred.'),
            ('2. Fire Detection', 'Linear heat detection cables and multi-sensor smoke detectors shall be installed in all AC coaches. Detection system shall interface with the train management system.'),
            ('3. Suppression Systems', 'Engine compartments of diesel locomotives shall have automatic fire suppression. Water mist systems are recommended for passenger coaches.'),
            ('4. Evacuation Plan', 'Emergency exits, luminescent pathway markings, and emergency hammers shall be provided as per latest RDSO guidelines.'),
        ],
    },
    {
        'document_id': 'RDSO-SF-002',
        'name': 'Derailment Investigation Procedures',
        'version': '1.8',
        'categories': ['Safety'],
        'sections': [
            ('1. Immediate Actions', 'Upon derailment, the Guard and Loco Pilot must protect the site, inform the nearest station, and arrange medical aid if casualties occur.'),
            ('2. Evidence Collection', 'Track parameters (gauge, cross-level, alignment), wheel profiles, and brake block conditions must be recorded before re-railment. Photographs from multiple angles are mandatory.'),
            ('3. Root Cause Analysis', 'Root cause analysis shall follow the fishbone (Ishikawa) methodology. Categories include Track, Rolling Stock, Human Factor, and External causes.'),
        ],
    },
    {
        'document_id': 'RDSO-GN-001',
        'name': 'Guidelines for Vendor Registration',
        'version': '7.0',
        'categories': ['General'],
        'sections': [
            ('1. Eligibility', 'Vendors must have a minimum 3-year track record in the relevant field. ISO 9001 certification is mandatory. Annual turnover requirements vary by item category.'),
            ('2. Application Process', 'Vendors shall apply through the RDSO Vendor Registration Portal with supporting documents including financial statements, quality certifications, and product test reports.'),
            ('3. Capacity Assessment', 'RDSO inspection team will conduct a factory assessment. Manufacturing capacity, quality control setup, and testing facilities will be evaluated.'),
            ('4. Renewal', 'Registration is valid for 5 years. Renewal applications must be submitted 6 months before expiry with updated documentation.'),
        ],
    },
    {
        'document_id': 'RDSO-GN-002',
        'name': 'Standard Drawings and Specifications Directory',
        'version': '2024-Q1',
        'categories': ['General'],
        'sections': [
            ('1. Purpose', 'This directory catalogues all current RDSO standard drawings and specifications across directorates. It is updated quarterly.'),
            ('2. Classification', 'Documents are classified by directorate: Carriage, Loco, Bridges & Structures, Track, Signal & Telecom, Electrical, Motive Power, and Quality Assurance.'),
            ('3. Superseded Documents', 'All superseded document numbers are listed with their replacement references. Use of superseded documents is prohibited.'),
        ],
    },
    {
        'document_id': 'RDSO-RS-003',
        'name': 'Specification for Train-18 (Vande Bharat) Chair Cars',
        'version': '1.2',
        'categories': ['Rolling Stock'],
        'sections': [
            ('1. Overview', 'This specification covers semi-high-speed, self-propelled EMU chair cars (Train-18 / Vande Bharat). Design speed: 180 km/h, operational speed: 160 km/h.'),
            ('2. Car Body', 'Stainless steel car body with aerodynamic front end. Fully sealed gangway connections between coaches. Automatic plug doors on both sides.'),
            ('3. Traction & Braking', 'Distributed power with underfloor traction equipment. Regenerative braking as primary. Disc brakes and magnetic track brakes as secondary systems.'),
            ('4. Passenger Amenities', 'WiFi, infotainment screens, bio-vacuum toilets, automatic sliding doors, modular pantry with hot case and coffee vending machines.'),
        ],
    },
    {
        'document_id': 'RDSO-TB-003',
        'name': 'Design of High-Speed Track for DFC',
        'version': '1.0',
        'categories': ['Track & Bridges'],
        'sections': [
            ('1. Alignment', 'Dedicated Freight Corridor (DFC) track alignment shall maintain a minimum curve radius of 2500 m. Gradient shall not exceed 1 in 200 for loaded direction.'),
            ('2. Track Structure', 'Slab track or heavy-duty ballasted track with 68 kg UIC rails. PSC sleepers at 600 mm spacing with Pandrol e-clips.'),
            ('3. Design Loads', 'Axle load: 25 tonnes. Annual traffic density: 200 EMTPA (Equivalent Million Tonnes Per Annum). Dynamic impact factor: 1 + (speed/600).'),
        ],
    },
    {
        'document_id': 'RDSO-EL-003',
        'name': 'Solar Power Integration for Railway Stations',
        'version': '1.1',
        'categories': ['Electrical', 'General'],
        'sections': [
            ('1. Introduction', 'Indian Railways aims to achieve net-zero carbon emissions by 2030. Solar installations at stations are a key initiative. This document specifies guidelines for rooftop and ground-mounted solar plants.'),
            ('2. System Design', 'Solar plants shall use monocrystalline or polycrystalline PV modules with minimum 20% efficiency. System capacity shall be sized to meet at least 50% of station energy demand.'),
            ('3. Grid Integration', 'Net metering with bi-directional energy meters is mandatory. Power conditioning units shall comply with IEEE 1547 for grid synchronization.'),
        ],
    },
]

USERS = [
    {'HRMS_ID': 'ADMIN01', 'password': 'admin123pass', 'email': 'admin01@railway.gov.in', 'phone': '9876543210', 'status': 'accepted', 'is_staff': True, 'is_superuser': True},
    {'HRMS_ID': 'EMP1001', 'password': 'emp1001pass', 'email': 'emp1001@railway.gov.in', 'phone': '9876543211', 'status': 'accepted', 'is_staff': False, 'is_superuser': False},
    {'HRMS_ID': 'EMP1002', 'password': 'emp1002pass', 'email': 'emp1002@railway.gov.in', 'phone': '9876543212', 'status': 'accepted', 'is_staff': False, 'is_superuser': False},
    {'HRMS_ID': 'EMP1003', 'password': 'emp1003pass', 'email': 'emp1003@railway.gov.in', 'phone': '9876543213', 'status': 'pending', 'is_staff': False, 'is_superuser': False},
    {'HRMS_ID': 'EMP1004', 'password': 'emp1004pass', 'email': 'emp1004@railway.gov.in', 'phone': '9876543214', 'status': 'rejected', 'is_staff': False, 'is_superuser': False},
    {'HRMS_ID': 'EMP1005', 'password': 'emp1005pass', 'email': 'emp1005@railway.gov.in', 'phone': '9876543215', 'status': 'accepted', 'is_staff': False, 'is_superuser': False},
]

FEEDBACK_COMMENTS = [
    'This document is very helpful for daily operations.',
    'Section 3 needs to be updated with the latest IS code references.',
    'Please add a checklist appendix for field staff.',
    'The tolerances mentioned in section 2 differ from the field manual. Kindly verify.',
    'Good document. Suggest adding illustrations for maintenance procedures.',
    'Can we get a Hindi translation of this specification?',
    'Excellent reference material. Shared with my team.',
    'Some figures are not legible in print. Please use higher resolution images.',
    'Request inclusion of FAQs based on common field queries.',
    'Version update needed to reflect circular RB/2024/01.',
    'Very comprehensive. Used this for the recent POH schedule.',
    'The safety norms referenced here should be cross-linked with RDSO-SF-001.',
]


# ── PDF generation ────────────────────────────────────────────────────

def generate_pdf(filepath, doc_info):
    """Generate a realistic multi-page PDF using reportlab."""
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        'DocTitle', parent=styles['Title'], fontSize=18,
        spaceAfter=6, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'], fontSize=11,
        alignment=TA_CENTER, textColor=colors.grey,
        spaceAfter=20,
    ))
    styles.add(ParagraphStyle(
        'SectionHeading', parent=styles['Heading2'], fontSize=13,
        spaceBefore=18, spaceAfter=8, textColor=colors.HexColor('#1a3c6e'),
    ))
    styles.add(ParagraphStyle(
        'BodyJustify', parent=styles['Normal'], fontSize=10,
        alignment=TA_JUSTIFY, leading=14, spaceAfter=10,
    ))

    elements = []

    # Header table (simulates RDSO letterhead)
    header_data = [
        ['RESEARCH DESIGNS & STANDARDS ORGANISATION', ''],
        ['Ministry of Railways, Lucknow - 226011', ''],
        [f"Document No: {doc_info['document_id']}", f"Version: {doc_info['version']}"],
    ]
    header_table = Table(header_data, colWidths=[12 * cm, 5 * cm])
    header_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (0, 0), 12),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, 1), colors.HexColor('#1a3c6e')),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.HexColor('#1a3c6e')),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 10),
        ('ALIGN', (1, 2), (1, 2), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 1 * cm))

    # Title
    elements.append(Paragraph(doc_info['name'], styles['DocTitle']))
    elements.append(Paragraph(
        f"Document ID: {doc_info['document_id']}  |  Version: {doc_info['version']}",
        styles['DocSubtitle'],
    ))

    # Metadata table
    today = timezone.now().strftime('%d-%m-%Y')
    meta_data = [
        ['Issued By', 'RDSO, Lucknow'],
        ['Date of Issue', today],
        ['Classification', ', '.join(doc_info['categories'])],
        ['Status', 'Current'],
    ]
    meta_table = Table(meta_data, colWidths=[4 * cm, 13 * cm])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8eef5')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.8 * cm))

    # Sections
    for heading, body in doc_info['sections']:
        elements.append(Paragraph(heading, styles['SectionHeading']))
        # Split body into paragraphs for a more natural look
        for para in body.split('. '):
            para = para.strip()
            if para and not para.endswith('.'):
                para += '.'
            if para:
                elements.append(Paragraph(para, styles['BodyJustify']))

    # Footer note
    elements.append(Spacer(1, 1.5 * cm))
    elements.append(Paragraph(
        '<i>This document is the property of RDSO. Unauthorised reproduction or distribution is prohibited.</i>',
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(elements)


# ── Command ───────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Populate the database with mock users, categories, documents (with generated PDFs), posts, and audit logs.'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Delete all existing data before populating')

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing data...')
            AuditLog.objects.all().delete()
            Post.objects.all().delete()
            Document.objects.all().delete()
            Category.objects.all().delete()
            User.objects.all().delete()

        # ── PDF directory ────────────────────────────────────────
        pdf_dir = os.path.join(settings.MEDIA_ROOT, 'documents')
        os.makedirs(pdf_dir, exist_ok=True)

        # ── Users ────────────────────────────────────────────────
        users = {}
        for u in USERS:
            if User.objects.filter(HRMS_ID=u['HRMS_ID']).exists():
                users[u['HRMS_ID']] = User.objects.get(HRMS_ID=u['HRMS_ID'])
                self.stdout.write(f"  User {u['HRMS_ID']} already exists, skipping")
                continue
            if u['is_superuser']:
                user = User.objects.create_superuser(
                    HRMS_ID=u['HRMS_ID'], password=u['password'],
                    email=u['email'], phone_number=u['phone'],
                )
            else:
                user = User.objects.create_user(
                    HRMS_ID=u['HRMS_ID'], password=u['password'],
                    email=u['email'], phone_number=u['phone'],
                )
            user.user_status = u['status']
            user.save()
            users[u['HRMS_ID']] = user
            self.stdout.write(f"  Created user {u['HRMS_ID']} ({u['status']})")

        # ── Categories ───────────────────────────────────────────
        categories = {}
        for name in CATEGORIES:
            cat, created = Category.objects.get_or_create(name=name)
            categories[name] = cat
            if created:
                self.stdout.write(f"  Created category: {name}")

        # ── Documents & PDFs ─────────────────────────────────────
        base_url = 'http://127.0.0.1:8000'
        accepted_users = [u for u in users.values() if u.user_status == 'accepted' and not u.is_superuser]
        all_accepted = [u for u in users.values() if u.user_status == 'accepted']
        now = timezone.now()

        for i, doc_info in enumerate(DOCUMENTS):
            doc_id = doc_info['document_id']
            if Document.objects.filter(document_id=doc_id).exists():
                self.stdout.write(f"  Document {doc_id} already exists, skipping")
                continue

            # Generate PDF
            pdf_filename = f"{doc_id}.pdf"
            pdf_path = os.path.join(pdf_dir, pdf_filename)
            generate_pdf(pdf_path, doc_info)
            self.stdout.write(f"  Generated PDF: {pdf_filename}")

            # Create document record
            doc = Document.objects.create(
                document_id=doc_id,
                name=doc_info['name'],
                version=doc_info['version'],
                link=f'{base_url}/api/documents/{doc_id}/pdf/',
                internal_link=f'{base_url}/api/documents/{doc_id}/pdf/',
            )
            for cat_name in doc_info['categories']:
                doc.category.add(categories[cat_name])

            # Backdate last_updated randomly over past 90 days
            backdated = now - timedelta(days=random.randint(1, 90))
            Document.objects.filter(pk=doc.pk).update(last_updated=backdated)

            # Audit log for document creation
            AuditLog.objects.create(
                user=users['ADMIN01'],
                action='document_create',
                target_type='document',
                target_id=doc_id,
                metadata={'name': doc_info['name']},
                created_at=backdated,
            )
            self.stdout.write(f"  Created document: {doc_id} - {doc_info['name']}")

        # ── Feedback / Posts ─────────────────────────────────────
        documents = list(Document.objects.all())
        for doc in documents:
            # 2-4 feedback items per document
            num_feedback = random.randint(2, 4)
            for _ in range(num_feedback):
                author = random.choice(all_accepted)
                post = Post.objects.create(
                    user=author,
                    post_type='feedback',
                    content=random.choice(FEEDBACK_COMMENTS),
                    document=doc,
                )
                post.created_at = now - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
                Post.objects.filter(pk=post.pk).update(created_at=post.created_at)

                AuditLog.objects.create(
                    user=author,
                    action='post_create',
                    target_type='document',
                    target_id=doc.document_id,
                    created_at=post.created_at,
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone! Created {User.objects.count()} users, "
            f"{Category.objects.count()} categories, "
            f"{Document.objects.count()} documents (with PDFs), "
            f"{Post.objects.count()} posts, "
            f"{AuditLog.objects.count()} audit log entries."
        ))
        self.stdout.write(self.style.SUCCESS(f"PDFs saved to: {pdf_dir}"))
        self.stdout.write('\nTest credentials:')
        self.stdout.write('  Admin:  ADMIN01 / admin123pass')
        self.stdout.write('  User:   EMP1001 / emp1001pass')
        self.stdout.write('  User:   EMP1002 / emp1002pass')
