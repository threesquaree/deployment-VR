from py2neo import Graph, Node, Relationship

graph = Graph(
        scheme="neo4j",
        host="localhost",
        port=7687,
        auth=("neo4j", "12345678"))

def create_graph(graph):
    # Create nodes
    try:
        gallery = Node("Environment", name="HERE: Black in Rembrandt’s Time")
        p1 = Node("Object", "Painting",
                  objectName = "C6",
                  name="The African King Caspar",
                  year="1654",
                  description="The painting represents one of the three magi who came to worship the Christ child. The three magi, additionally known as the three wisemen visited Jesus, bearing precious gift in celebration of his birth. Caspar, the second oldest magi, gifted the golden vessel filled with incense as to represent Jesus' deity. In the bible the magi were referred to as the 'men who study the stars', and believed to be astrologers who predicted the birth of Jesus by their ability to read the messages that were hidden in the sky. Sometimes he is called Caspar, sometimes Balthasar. Heerschop painted him without surroundings or story. He can only be identified from his expensive clothes and the jar of incense he gave as his gift. But it is the man's face that attracts the most attention; he looks at us proudly and self-confidently.",
                  moreInfo = "The African King Caspar depicts the Biblical King Caspar from the Adoration of the Magi. In the Biblical story, three wise kings, or magi, approached the infant Jesus with gifts. King Melchior, the oldest magi, brought gold to represent the infant’s regality. The second oldest magi, King Caspar, brought frankincense to represent the infant’s divinity, while King Balthasar, the youngest magi, brought myrrh to represent the infant’s humanity. Hendrik Heerschop’s The African King Caspar depicts the magi holding his gift of frankincense. It is inside the precious vessel between his hands. What is ultimately sad about Hendrik Heerschop’s The African King Caspar is that we know so little about the artist and the sitter. We know Hendrik Heerschop worked in Haarlem, Netherlands. He created genre scenes, and painted in the style of Haarlem classicism. The sitter, however, is unknown. History has forgotten his name. On the other hand, what we do know is that the depicted in The African King Caspar has the facial features of a specific individual. That is to say, this African man is not a generic composition (tronie). He is not an idealized or imaginary model. Slavery was not allowed in the Netherlands during the 17th century, therefore the African sitter was free and may have been a neighbor or an acquaintance of the artist. This probably means what we have in The African King Caspar is a free African man being painted in the guise of an African king by a white Dutch artist who specialized in genre scenes.",
                  style="Oil on panel. The painting of King Caspar was made using oil paints applied on oak wood panel, known for its durability and little warping when exposed to sunlight. The painting can be seen as a prime example of Haarlem classism, often characterised by a rather naturalistic painting style and depictions of a prosaic or ordinary subject matter. In this painting Hendrick plays with the images lighting, putting the focus on King Caspar’s face and his expression, showing dignity and grandeur.",
                  location="Gemäldegalerie, Berlin",
                  period = "'Dutch Golden Age', start: 1581, end: 1672. It was a time when the Dutch Republic was among the leading nations for art, trade, science, and military.",
                  artist="Hendrick Heerschop. The Dutch illustrator and painter Hendrick Heerschop was born in 1626 and passed away in 1690. He was the Son of the Haarlem Harmen Jasz and the apprentice of Willem Claesz, another Dutch golden age painter popular due to his still life compositions. Hendrick on the other hand was mostly known for his portraits and genre scenes, a form of art that depicted aspects of everyday life by the portrayal of ordinary people engaging in common activities.  ",
                  img="https://www.wikidata.org/wiki/Q94997800#/media/File:Hendrick-Heerschop-Koning-Caspar-1654.-Olieverf-op-paneel.-Berlijn-Staatliche-Museen.jpg",
                  AOIs= ["King Caspar","Incense Pot", "Golden Accessories (necklace, earring, ring)", "Doublet", "Gemstones"]
                  )

        p2 = Node("Object", "Painting",
                  objectName="C5",
            name="Head of a Boy in a Turban",
            year="1635",
            description="Dou was Rembrandt's first pupil. He took up his master's idea of studying black people. The painting depicts an endearing tronie of a young boy dressed in a fantasy costume, who looks at us over his shoulder. A tronie was a painting genre commonly used from the 15th until the 17th century and originated from Italy. Such portrait studies depict the bust of a nameless model against a neutral background. Tronies showed great skills of the artist, often used as exercises for the portrayal of age, character and emotion. In the golden age there was a lively market for such exercises, often sold as independent works of art.",
            style="The painting was made using oil paints applied on panel. The paintings of Gerrit Dou were known for their immense perfection and attention to detail. Additionally, he perfected the light and dark effects also known as Chairoscuro, an Italian painting style where light and shadows are often depicted stronger and more dramatic than they often are in real life. However, his technique eventually lead to a decline in his status as an artist, as his clients did not have the time to pose for an extensive amount of time. ",
            location="Hannover, Landesmuseum",
            artist="Gerrit Dou, additionally known as Gerard Dou was born in Leiden in 1613 and died in 1675. Although originally apprenticed by his father Douwe Jansz, a glass painter, Gerrit became the first pupil of Rembrandt later on in life. He took up his masters idea of studying people of colour, resulting in tronies such as the one presented here.",
            img="https://upload.wikimedia.org/wikipedia/commons/9/9b/Portrait_of_a_Boy%2C_Gerrit_Dou%2C_c._1630%2C_oil_on_panel%2C_42_by_33.5_cm%2C_Nieders%C3%A4chsisches_Landesmuseum_Hanover.jpg",
            AOIs=["Turban", "White ostrich feather", "Blue garment"]
        )

        p3 = Node("Object", "Painting",
                  objectName="B2",
            name="Portrait of Dom Miguel de Castro",
            year="1643",
            description="Dom Miguel de Castro makes here a powerful, serious expression. He was a member of the Congolese elite. This portrait was commissioned by the Dutch West India Company. The WIC and the Congolese rulers traded in gold an ivory, but mainly in people. This is why Dom Miguel now is seen as a controversial figure. Dom Miguel wears fashionable European clothes. This is probably the suit he had acquired in Brazil, when he had visited the Dutch colony earlier.De Castro was sent as an envoy to the Dutch Republic, asking the Dutch stadtholder for a mediation in a conflict that the Count had with king Garcia II of Congo. The portrait was created during his two week stay in Middelburg as part of six commissioned paints. Two of these additional paintings portraying both of his servants Diego Bemba and Pedro Sunda.",
            moreInfo = "The name of Dom Miguel de Castro reads on the reverse of a third painting in the series. A blue cloudy sky over a small brim of open sea forms the background. Dom Miguel turns slightly to the right, just as the two other men. He gazes out at the beholder with a serious expression. He is dressed in a brown woollen riding coat with hanging sleeves over a silver brocade suit. The top of the silver handle of a sword, carried in a fancy decorated cross belt, peeps over the lower edge of the painting. The wide brimmed hat with a red ostrich feather was also fashionable in Europe in the 1640s and 50s. A remarkable feature is that two gold counters are stuck in the hat's silver ribbon.",
            style="The portrait of Dom Miguel de Castro was made using oil paints on oak wood panel. The identification of the base material of the panel lead to the correct attribution of the original painter of the portrait. At the time of its creation oak wood was not readily available in Brazil, indicating that the portrait must have been created somewhere in Europe.",
            location="Statensmuseum for Kunst, Copenhagen",
            artist="Jeronimus Beckx. Originally, the portrait of Dom Miguel de Castro was thought to be created by Albert Eckhout, a Dutch portrait and still life painter. This painting, together with 20 Brazilian paintings by Albert Eckhout were donated to king Frederick III of Denmark, which eventually led to them ending up at the National Gallery of Denmark. Due to these circumstances, the painting was wrongly attributed to Albert Eckhout. It is however currently thought that the portrait was created during Dom Miguel de Castros stay in Middelburg, assumed to be painted by one of the brothers Jasper or Jeronimus Beckx.",
            img="https://open.smk.dk/artwork/iiif/KMS7",
            AOIs=["Red ostrich feather", "Cavalier hat", "Gilt garment"]
        )

        p4 = Node("Object", "Painting",
                  objectName="B3",
                  name="Portrait of Pedro Sunda",
                  year="1643",
                  description="Pedro Sunda holds an elephant's tusk. Ivory was one of the Congo's major export products. The status of these young men is unclear. Were they assistants of the noble Dom Miguel or were they enslaved?",
                  moreInfo="""The Congolese man is dressed according to European fashion around the 1640s and 50s. He wears a green velvet suit with golden ribbons and buttons and a large white collar like the ones sported by the Spanish king at the time, only without lace edges. His body is turned slightly to the right while he gazes to the rear, as if somebody or something demands his attention. With his right arm, he supports a large and heavy elephant tusk and with a firm grip holds the pointed end upwards with the other hand. A soft light comes from a high window outside the picture space. The shadows cast from the window edge and from his own head frames his dark face on a light brown background. Although it is only a half figure portrait, the artist has created a dynamic and vivid composition thanks to the juxtaposed movement of the sitter's body, the direction of his eyes, the shadow to the left and the bended diagonal of the elephant tusk. This vividness is combined with a severe palette consisting of a beautiful combination of green, brown and whitish hues. An inscription on the reverse of the painting identifies the man as Pedro Sunda, which tells us that he was a baptised Christian.
                    The inscription "Pedro Sunda" on the back is important because it tells us who the person portrayed is. The portrait belongs to a series of three paintings, all of which have names on the back. In addition to Pedro Sunda, the names Diego Bemba and Dom Michael de Castro are written on the other two paintings. Thanks to the inscriptions on the back, we can reconstruct the history of the paintings. Dom Michael de Castro was on a diplomatic mission for the Count of Sonho (Soyo), Daniel da Silva, in the then Congo and part of a delegation that had to meet the head of the Dutch Republic, Governor Frederick Hendrick, and the governor of Dutch Brazil, Johan Mauritz, Count of Nassau-Siegen. The goal was to gather allies in a territorial dispute in the homeland. With him he had his two servants, Pedro Sunda and Diego Bemba.
                    The very special thing about the painting is that this African is dressed according to European fashion and thereby equates himself, so to speak, with the European colonial power. He looks back over his shoulder as if to communicate with someone or something outside the picture frame. An inscription on the back of the painting tells us that we are facing a portrait of Pedro Sunda, who was the servant of the Congolese envoy Don Miguel de Castro. Portraits of named servants from Africa are rare in the history of art. Pedro Sunda was part of a delegation seeking help in resolving a territorial dispute in their homeland. First, the delegation traveled to Dutch Brazil and then to the Netherlands to gather supporters. The precious elephant tusk was perhaps one of the gifts the delegation brought. They were expensive and rare collectibles that every prince would like to own and display in his art chamber.
                    The African looks back. His attention is directed to something outside the picture frame. He is as if caught between his own impact shadow and a diagonal impact shadow from a high window that we cannot see. The shadows on the wall create the illusion of space and give the composition dynamism in the play between diagonal courses. With their clarity, the shadows give the painting an atmosphere of something serious and dramatic. An inscription on the back of the painting tells us that we are facing a portrait of Pedro Sunda, who was the servant of the Congolese envoy Don Miguel de Castro. Portraits of named servants from Africa are rare in the history of art. Pedro Sunda was part of a delegation seeking help in resolving a territorial dispute in their homeland. First, the delegation traveled to Dutch Brazil and then to the Netherlands to gather supporters. The elephant tusk was one of the gifts the delegation brought.""",
                  style="Oil on panel",
                  location="Statensmuseum for Kunst, Copenhagen",
                  artist="Jeronimus Beckx",
                  img="https://open.smk.dk/artwork/iiif/KMS8",
                  AOIs=[
                      "The ivory tusk"
                  ]
                  )
        p5 = Node("Object", "Painting",
                  objectName="B1",
            name="Portrait of Diego Bemba",
            year="1643",
            description="We know the names of these three men from the inscriptions on the backs of the paintings. This is Diego Bemba. He holds a small casket, probably a diplomatic gift. He was one of Don Miguel de Castro's servants.",
            moreInfo = "The inscription on the reverse of the pendant piece reads Diego Bemba. Diego wears the same type of clothes as his companion and is placed in the same framing of shadows. His body too is turned slightly to the right and he carries a small artisanal box which he points at with his index finger. His eyes are turned upwards as if he were addressing or giving thanks to God. This gesture makes it plausible that the box contains something holy, a saint's relic or obols.",
            style="Oil on panel",
            location="Statensmuseum for Kunst, Copenhagen",
            artist="Jeronimus Beckx",
            img="https://open.smk.dk/artwork/iiif/KMS9",
            AOIs=[
                "Box"
            ]
        )

        p1a1 = Node("AOI",
            name="Incense Pot",
            description="The golden pot in the painting represents an incense pot, a gift for Jesus. Presented in an ornately decorated golden container and thus expressing its worth, as explained in the bible, the gold represented the kingship of Jesus. In the bible the incense was given as one of the three gifts after the birth of Jesus. The objects shown in this painting specifically is frankincense, which embodied Jesus’ deity. In the old testament frankincense was typically burnt in temples as an offering for god. With King Caspar gifting this to Jesus, he affirms that Jesus is both man and god. Additionally frankincense was thought to have healing powers, used in the east as a traditional healing method."
        )
        p1a21 = Node("AOI",
            name="Necklace",
            description="In the painting Caspar is seen wearing different types of golden accessories (for example, necklace, earring, ring). Due to its rarity and unique colour gold was often used in paintings as a form of symbolism. Gold would represent the high power and status of the wearer. The 17th century was often thought as the age of elegance when it comes to accessories. The sprinkling of jewels to show power was replaced by the wearing of a few carefully selected statement pieces to show taste. Finely carved rings, such as the one worn by King Caspar, were the preferred type of jewel worn by nobles.Additionally gold often represented the light of god in Christian art."
        )
        p1a22 = Node("AOI",
                    name="Earring",
                    description="In the painting Caspar is seen wearing different types of golden accessories (for example, necklace, earring, ring). Due to its rarity and unique colour gold was often used in paintings as a form of symbolism. Gold would represent the high power and status of the wearer. The 17th century was often thought as the age of elegance when it comes to accessories. The sprinkling of jewels to show power was replaced by the wearing of a few carefully selected statement pieces to show taste. Finely carved rings, such as the one worn by King Caspar, were the preferred type of jewel worn by nobles.Additionally gold often represented the light of god in Christian art."
                    )
        p1a23 = Node("AOI",
                    name="Ring",
                    description="In the painting Caspar is seen wearing different types of golden accessories (for example, necklace, earring, ring). Due to its rarity and unique colour gold was often used in paintings as a form of symbolism. Gold would represent the high power and status of the wearer. The 17th century was often thought as the age of elegance when it comes to accessories. The sprinkling of jewels to show power was replaced by the wearing of a few carefully selected statement pieces to show taste. Finely carved rings, such as the one worn by King Caspar, were the preferred type of jewel worn by nobles.Additionally gold often represented the light of god in Christian art."
                    )
        p1a3 = Node("AOI",
            name="Doublet",
            description="The man in the painting is seen wearing a yellow doublet paired with an intricately detailed and jewelled cloak. A doublet is a type of form fitted waist length jacket worn with the aims of adding shape and padding to the body, often made from linen or wool which would help keep the wearer warm. Additionally, the colour yellow was often associated with the sun and was seen as a connection to god in many religions."
        )
        p1a4 = Node("AOI",
                    name="Gemstones",
                    description="Due to the expanding global trade in the 17th century, gemstones became more available."
                    )
        p1a5 = Node("AOI",
                    name="King Caspar",
                    description="One of the three magi who came to worship the Christ child. The three magi, additionally known as the three wisemen visited Jesus, bearing precious gift in celebration of his birth. Caspar, the second oldest magi, gifted the golden vessel filled with incense as to represent Jesus' deity. In the bible the magi were referred to as the 'men who study the stars', and believed to be astrologers who predicted the birth of Jesus by their ability to read the messages that were hidden in the sky. Sometimes he is called Caspar, sometimes Balthasar."
                    )

        p2a1 = Node("AOI",
            name="Turban",
            description="A turban is a type of headwear constructed by the winding of cloth. It was often made from strong fabrics such as cotton and worn as customary headwear by people of various cultures."
        )
        p2a2 = Node("AOI",
            name="White ostrich feather",
            description="The feather seen in the painting forms a type of decoration on the turban worn by the boy. The addition of elements of nature was deemed as a way of honouring culture and land. In many cultures a white feather is seen as a sign of hope or peace."
        )
        p2a3 = Node("AOI",
            name="Blue garment",
            description="The garment worn by the boy represents a fantasy costume, with elements from a variety of styles from 17th century clothing. During this time, the pigment blue was the most lavish and difficult to obtain. It was the colour of power and royalty and represented self-worth."
        )
        p2a4 = Node("AOI",
                    name="Young boy",
                    description="The painting depicts an endearing tronie of a young boy dressed in a fantasy costume, who looks at us over his shoulder. A tronie was a painting genre commonly used from the 15th until the 17th century and originated from Italy. Such portrait studies depict the bust of a nameless model against a neutral background. Tronies showed great skills of the artist, often used as exercises for the portrayal of age, character and emotion. ",
                    )

        p3a1 = Node("AOI",
            name="Red ostrich feather",
            description="The feather Dom Miguel de Castro is shown wearing is an ostrich feather. Such feather were often seen as a symbol of elegance or luxurious extravagance. The colour red was often associated with wealth and power, due to fact that it was the first colour ever developed for painting and dyeing. The wearing of feathers on a headdress indicated a sign of status wealth and ethnicity. Often, the wearing of more rare and unusual items  would indicate a higher societal status."
        )
        p3a2 = Node("AOI",
            name="Cavalier hat",
            description="The cavalier hat was a commonly worn wide-brimmed hat from the 17th century. The name of this hat originates from supports of King Charles I, known as the Cavaliers, who were known for wearing extravagant garments. The hats were often made from felt and accentuated with ostrich feathers, secured on the hat with a broach. One side was often pinned to its base, creating an asymmetrical look."
        )
        p3a3 = Node("AOI",
            name="Gilt garment",
            description="The garment worn by Dom Miguel de Castro is ornately decorated with silver gilt embroidery, using metal threads. Silver often symbolized wealth, grace and elegance. Additionally, the garment includes a plain falling band, a commonly worn collar during the 17th century. Such bands were often made from sheer, white fabric such as linen without additional lace on the edges."
        )

        p3a4 = Node("AOI",
                    name="Dom Miguel",
                    description="Dom Miguel de Castro makes here a powerful, serious expression. He was a member of the Congolese elite.")

        p4a1 = Node("AOI",
            name="Ivory tusk",
            description="Pedro Sunda is shown holding the tusk of an elephant. The material of a tusk, ivory, was deemed very valuable due to its beauty and durability, substantially exported due to its high demand. Additionally, the material was used as a way to craft objects or carve depictions, so called ivories.Throughout history, a tusk as a whole often represented strength and power."
        )

        p4a2 = Node("AOI",
                    name="Pedro Sunda",
                    description="Pedro Sunda, who was the servant of the Congolese envoy Don Miguel de Castro. Portraits of named servants from Africa are rare in the history of art. Pedro Sunda was part of a delegation seeking help in resolving a territorial dispute in their homeland. First, the delegation traveled to Dutch Brazil and then to the Netherlands to gather supporters. The precious elephant tusk was perhaps one of the gifts the delegation brought."
                    )

        p4a3 = Node("AOI",
                    name="Cloth",
                    description="He wears a green velvet suit with golden ribbons and buttons and a large white collar like the ones sported by the Spanish king at the time, only without lace edges. His body is turned slightly to the right while he gazes to the rear, as if somebody or something demands his attention. With his right arm, he supports a large and heavy elephant tusk and with a firm grip holds the pointed end upwards with the other hand. This African is dressed according to European fashion and thereby equates himself, so to speak, with the European colonial power.")


        p5a1 = Node("AOI",
            name="Box",
            description="The small casket held by Diego Bemba is assumed to be a diplomatic gift. Such gifts were given by a diplomat or leader as a courtesy when entering a foreign country. A decorative box such as the one presented in the painting, was more than a functional packaging, complemented with artistic elements."
        )

        p5a2 = Node("AOI",
                    name="Diego Bemba",
                    description="This is Diego Bemba. He was one of Don Miguel de Castro's servants."
                    )

        p5a3 = Node("AOI",
                    name="Clothes",
                    description="Diego wears the same type of clothes as his companion (Pedro Sunda) and is placed in the same framing of shadows. His body too is turned slightly to the right and he carries a small artisanal box which he points at with his index finger."
                    )



        # Create relationships
        gallery_p1 = Relationship(gallery, "has_object", p1)
        gallery_p2 = Relationship(gallery, "has_object", p2)
        gallery_p3 = Relationship(gallery, "has_object", p3)
        gallery_p4 = Relationship(gallery, "has_object", p4)
        gallery_p5 = Relationship(gallery, "has_object", p5)

        p1_a1 = Relationship(p1, "has_AOI", p1a1)
        p1_a21 = Relationship(p1, "has_AOI", p1a21)
        p1_a22 = Relationship(p1, "has_AOI", p1a22)
        p1_a23 = Relationship(p1, "has_AOI", p1a23)
        p1_a3 = Relationship(p1, "has_AOI", p1a3)
        p1_a4 = Relationship(p1, "has_AOI", p1a4)
        p1_a5 = Relationship(p1, "has_AOI", p1a5)
        p2_a1 = Relationship(p2, "has_AOI", p2a1)
        p2_a2 = Relationship(p2, "has_AOI", p2a2)
        p2_a3 = Relationship(p2, "has_AOI", p2a3)
        p2_a4 = Relationship(p2, "has_AOI", p2a4)
        p3_a1 = Relationship(p3, "has_AOI", p3a1)
        p3_a2 = Relationship(p3, "has_AOI", p3a2)
        p3_a3 = Relationship(p3, "has_AOI", p3a3)
        p3_a4 = Relationship(p3, "has_AOI", p3a4)
        p4_a1 = Relationship(p4, "has_AOI", p4a1)
        p4_a2 = Relationship(p4, "has_AOI", p4a2)
        p4_a3 = Relationship(p4, "has_AOI", p4a3)
        p5_a1 = Relationship(p5, "has_AOI", p5a1)
        p5_a2 = Relationship(p5, "has_AOI", p5a2)
        p5_a3 = Relationship(p5, "has_AOI", p5a3)

        # Merge nodes and relationships into the graph
        #merge paintings
        graph.merge(gallery, "Environment", "name")
        graph.merge(p1, "Object", "name")
        graph.merge(p2, "Object", "name")
        graph.merge(p3, "Object", "name")
        graph.merge(p4, "Object", "name")
        graph.merge(p5, "Object", "name")
        graph.merge(p1, "Painting", "name")
        graph.merge(p2, "Painting", "name")
        graph.merge(p3, "Painting", "name")
        graph.merge(p4, "Painting", "name")
        graph.merge(p5, "Painting", "name")

        #merge artifacts
        graph.merge(p1a1, "AOI", "name")
        graph.merge(p1a21, "AOI", "name")
        graph.merge(p1a22, "AOI", "name")
        graph.merge(p1a23, "AOI", "name")
        graph.merge(p1a3, "AOI", "name")
        graph.merge(p1a4, "AOI", "name")
        graph.merge(p1a5, "AOI", "name")
        graph.merge(p2a1, "AOI", "name")
        graph.merge(p2a2, "AOI", "name")
        graph.merge(p2a3, "AOI", "name")
        graph.merge(p2a4, "AOI", "name")
        graph.merge(p3a1, "AOI", "name")
        graph.merge(p3a2, "AOI", "name")
        graph.merge(p3a3, "AOI", "name")
        graph.merge(p3a4, "AOI", "name")
        graph.merge(p4a1, "AOI", "name")
        graph.merge(p4a2, "AOI", "name")
        graph.merge(p4a3, "AOI", "name")
        graph.merge(p5a1, "AOI", "name")
        graph.merge(p5a2, "AOI", "name")
        graph.merge(p5a3, "AOI", "name")

        #merge relationships
        graph.merge(gallery_p1)
        graph.merge(gallery_p2)
        graph.merge(gallery_p3)
        graph.merge(gallery_p4)
        graph.merge(gallery_p5)

        graph.merge(p1_a1)
        graph.merge(p1_a21)
        graph.merge(p1_a22)
        graph.merge(p1_a23)
        graph.merge(p1_a3)
        graph.merge(p1_a4)
        graph.merge(p1_a5)
        graph.merge(p2_a1)
        graph.merge(p2_a2)
        graph.merge(p2_a3)
        graph.merge(p2_a4)
        graph.merge(p3_a1)
        graph.merge(p3_a2)
        graph.merge(p3_a3)
        graph.merge(p3_a4)
        graph.merge(p4_a1)
        graph.merge(p4_a2)
        graph.merge(p4_a3)
        graph.merge(p5_a1)
        graph.merge(p5_a2)
        graph.merge(p5_a3)

        print("Graph nodes and relationships created successfully!")

    except Exception as e:
        print(e)

create_graph(graph)
